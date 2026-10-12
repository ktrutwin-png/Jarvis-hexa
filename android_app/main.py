"""NexTrade Android entry point.

The first mobile shell exposes read-only market scanning, portfolio valuation
and encrypted Kraken credential storage. Live order submission is deliberately
not enabled.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import flet as ft
import flet_secure_storage as fss
from flet_android_notifications import FletAndroidNotifications, NotificationAction
from nextrade_background import NexTradeBackground

from heksa.core import HeksaCore
from heksa.kraken import KrakenClient
from heksa.market_config import WATCHLIST_ASSETS, fetch_market_catalog
from heksa.market_monitor import MarketMonitor
from heksa.portfolio import fetch_portfolio_eurc


APP_NAME = "NexTrade"
APP_VERSION = "0.3.3"
PROPOSAL_NOTIFICATION_ID = 9002
KRAKEN_API_KEY = "nextrade.kraken.api_key"
KRAKEN_PRIVATE_KEY = "nextrade.kraken.private_key"

BG = "#071021"
SURFACE = "#101A31"
SURFACE_2 = "#16213E"
ACCENT = "#6F7CFF"
ACCENT_2 = "#A855F7"
TEXT = "#F4F7FF"
MUTED = "#9AA7C2"
SUCCESS = "#35D07F"
WARNING = "#F5B942"
DANGER = "#FF6376"


class NexTradeAndroidApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        storage_dir = os.environ.get("FLET_APP_STORAGE_DATA")
        data_dir = Path(storage_dir) / "heksa" if storage_dir else None
        self.core = HeksaCore(data_dir=data_dir)
        self.monitor = MarketMonitor(self.core.data_dir)
        self.background = NexTradeBackground()
        self.notifications = FletAndroidNotifications(on_notification_tap=self._on_notification_tap)
        self.monitor_enabled = False
        self.monitor_transition = False
        self.monitor_error: str | None = None
        self.notified_proposal_id: str | None = None
        self.notification_retry_at = 0.0
        self.monitor_signature: str | None = None
        self.last_scan: dict[str, Any] | None = None
        self.portfolio_snapshot: dict[str, Any] | None = None
        self.credentials_configured = False
        self.scan_in_progress = False
        self.decision_in_progress = False
        self.scan_error: str | None = None
        self.market_catalog: list[dict] | None = None
        self.market_refresh_in_progress = False
        self.market_selection_in_progress = False
        self.market_error: str | None = None
        self.selected_assets = self.core.journal.market_selection()
        self.rejection_cooldown_field = ft.TextField(
            label="Pomijaj odrzuconą parę przez (minuty)",
            value=str(self.core.journal.rejection_cooldown_minutes()),
            keyboard_type=ft.KeyboardType.NUMBER,
            helper=ft.Text("1–1440 minut. Zmiana dotyczy kolejnych odrzuceń."),
        )

        self.storage = fss.SecureStorage(
            android_options=fss.AndroidOptions(
                reset_on_error=True,
                migrate_on_algorithm_change=True,
                enforce_biometrics=False,
                key_cipher_algorithm=fss.KeyCipherAlgorithm.AES_GCM_NO_PADDING,
                storage_cipher_algorithm=fss.StorageCipherAlgorithm.AES_GCM_NO_PADDING,
                shared_preferences_name="nextrade_secure_storage",
                preferences_key_prefix="nextrade",
                biometric_prompt_title="NexTrade",
                biometric_prompt_subtitle="Potwierdź dostęp do kluczy Kraken",
            )
        )

        self.api_key_field = ft.TextField(
            label="Kraken API key",
            password=True,
            can_reveal_password=True,
            border_color=ACCENT,
        )
        self.api_secret_field = ft.TextField(
            label="Kraken private key",
            password=True,
            can_reveal_password=True,
            border_color=ACCENT,
        )
        self.credentials_status = ft.Text(
            "Sprawdzanie bezpiecznego magazynu…",
            color=MUTED,
        )

        self.body = ft.Container(expand=True, bgcolor=BG)
        self.navigation = ft.NavigationBar(
            selected_index=0,
            bgcolor=SURFACE,
            indicator_color=SURFACE_2,
            on_change=self._on_navigation_change,
            destinations=[
                ft.NavigationBarDestination(
                    icon=ft.Icons.HOME_OUTLINED,
                    selected_icon=ft.Icons.HOME,
                    label="Start",
                ),
                ft.NavigationBarDestination(
                    icon=ft.Icons.SHOW_CHART,
                    label="Sygnały",
                ),
                ft.NavigationBarDestination(
                    icon=ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED,
                    selected_icon=ft.Icons.ACCOUNT_BALANCE_WALLET,
                    label="Portfel",
                ),
                ft.NavigationBarDestination(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    selected_icon=ft.Icons.SETTINGS,
                    label="Ustawienia",
                ),
                ft.NavigationBarDestination(
                    icon=ft.Icons.LIST,
                    label="Rynki",
                ),
            ],
        )

        self._configure_page()
        self._show_view(0)
        self.page.run_task(self._refresh_credentials_status)
        self.page.run_task(self._refresh_market_catalog)
        self.page.on_app_lifecycle_state_change = self._on_lifecycle_change
        self.page.run_task(self._watch_monitor)

    def _configure_page(self) -> None:
        self.page.title = APP_NAME
        self.page.bgcolor = BG
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 0
        self.page.navigation_bar = self.navigation
        self.page.theme = ft.Theme(
            color_scheme_seed=ACCENT,
            use_material3=True,
        )
        self.page.add(
            ft.SafeArea(
                expand=True,
                content=self.body,
            )
        )

    def _on_navigation_change(self, event: ft.Event[ft.NavigationBar]) -> None:
        self._show_view(event.control.selected_index)

    def _show_view(self, index: int) -> None:
        views = (
            self._home_view,
            self._signals_view,
            self._portfolio_view,
            self._settings_view,
            self._markets_view,
        )
        safe_index = index if 0 <= index < len(views) else 0
        self.navigation.selected_index = safe_index
        self.body.content = views[safe_index]()
        self.page.update()

    def _screen(self, controls: list[ft.Control]) -> ft.Control:
        return ft.Container(
            expand=True,
            padding=18,
            content=ft.ListView(
                expand=True,
                spacing=14,
                controls=controls,
            ),
        )

    def _section_title(self, title: str, subtitle: str | None = None) -> ft.Control:
        controls: list[ft.Control] = [
            ft.Text(title, size=26, weight=ft.FontWeight.BOLD, color=TEXT),
        ]
        if subtitle:
            controls.append(ft.Text(subtitle, size=13, color=MUTED))
        return ft.Column(spacing=2, controls=controls)

    def _card(
        self,
        content: ft.Control,
        *,
        border_color: str | None = None,
    ) -> ft.Control:
        return ft.Container(
            padding=16,
            bgcolor=SURFACE,
            border=ft.Border.all(1, border_color or "#21304F"),
            border_radius=18,
            content=content,
        )

    def _home_view(self) -> ft.Control:
        scan_count = 0
        actionable = 0
        if self.last_scan:
            scan_count = int(self.last_scan.get("markets_scanned") or 0)
            actionable = int(self.last_scan.get("actionable_candidates") or 0)

        orb = ft.Container(
            width=184,
            height=184,
            alignment=ft.Alignment.CENTER,
            border_radius=92,
            gradient=ft.RadialGradient(
                center=ft.Alignment(-0.35, -0.45),
                radius=1.15,
                colors=["#E0E7FF", "#6F7CFF", "#3B1B7A", "#071021"],
                stops=[0.0, 0.28, 0.68, 1.0],
            ),
            shadow=[
                ft.BoxShadow(
                    blur_radius=38,
                    spread_radius=8,
                    color="#556F7CFF",
                )
            ],
            content=ft.Icon(ft.Icons.AUTO_GRAPH, size=56, color="#F8FAFF"),
        )

        status = self._card(
            ft.Column(
                spacing=10,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("Heksa Core", weight=ft.FontWeight.BOLD, color=TEXT),
                            ft.Text("ONLINE", color=SUCCESS, weight=ft.FontWeight.BOLD),
                        ],
                    ),
                    ft.Text(
                        "Tryb bezpieczny: analiza i propozycje. Aplikacja nie wysyła prawdziwych zleceń.",
                        color=MUTED,
                        size=13,
                    ),
                ],
            ),
            border_color="#27466A",
        )

        metrics = ft.Row(
            spacing=10,
            controls=[
                self._metric("Rynki", str(scan_count)),
                self._metric("Sygnały", str(actionable)),
                self._metric("Waluta", "EURC"),
            ],
        )

        return self._screen(
            [
                self._section_title(
                    APP_NAME,
                    f"Android • wersja {APP_VERSION}",
                ),
                ft.Container(
                    alignment=ft.Alignment.CENTER,
                    padding=ft.Padding.symmetric(vertical=22),
                    content=orb,
                ),
                status,
                metrics,
                self._monitor_card(),
                ft.Button(
                    "Skanuj rynek EURC",
                    icon=ft.Icons.REFRESH,
                    on_click=self._refresh_signals,
                    disabled=self.scan_in_progress or self.decision_in_progress,
                ),
            ]
        )

    def _metric(self, label: str, value: str) -> ft.Control:
        return ft.Container(
            expand=True,
            padding=12,
            bgcolor=SURFACE_2,
            border_radius=14,
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
                controls=[
                    ft.Text(value, size=20, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Text(label, size=11, color=MUTED),
                ],
            ),
        )

    def _monitor_card(self) -> ft.Control:
        state = "Włączone" if self.monitor_enabled else "Zatrzymane"
        controls = [
            ft.Text(f"Skanowanie w tle: {state}", color=TEXT, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Skan co 60 s po zakończeniu poprzedniego. Telefon może mieć zgaszony ekran. "
                "Włącz powiadomienia i zezwól na pracę bez optymalizacji baterii. "
                "Pozostaw NexTrade na liście ostatnich aplikacji — usunięcie go z tej listy zatrzymuje skaner.",
                color=MUTED, size=12,
            ),
            ft.Button(
                "Zatrzymaj skanowanie" if self.monitor_enabled else "Włącz skanowanie w tle",
                on_click=self._toggle_monitor,
                disabled=self.monitor_transition,
            ),
        ]
        if self.last_scan and self.last_scan.get("last_success_at"):
            controls.append(ft.Text(
                "Ostatni udany skan: " + self._display_time(self.last_scan["last_success_at"]),
                color=MUTED, size=12,
            ))
        if self.monitor_error:
            controls.append(ft.Text(self.monitor_error, color=WARNING, size=12))
        return self._card(ft.Column(controls=controls, spacing=8))

    async def _toggle_monitor(self, _event=None) -> None:
        if self.monitor_transition:
            return
        self.monitor_transition = True
        self.monitor_error = None
        self._show_view(self.navigation.selected_index)
        try:
            if self.monitor_enabled:
                await asyncio.to_thread(self.monitor.stop)
                self.monitor_enabled = False
                await self.background.stop()
                await self.notifications.cancel(PROPOSAL_NOTIFICATION_ID)
                self.notified_proposal_id = None
            else:
                if not await self.notifications.request_permissions():
                    self.monitor_error = "Zezwól na powiadomienia, aby odbierać propozycje."
                    return
                if not await self.background.start():
                    self.monitor_error = "Nie uruchomiono pracy w tle. Sprawdź zgodę na działanie bez ograniczeń baterii."
                    return
                await asyncio.to_thread(self.monitor.start)
                self.monitor_enabled = True
        except Exception:
            await asyncio.to_thread(self.monitor.stop)
            self.monitor_enabled = False
            self.monitor_error = "Nie udało się uruchomić lub zatrzymać trybu w tle. Spróbuj ponownie."
            try:
                await self.background.stop()
                await self.notifications.cancel(PROPOSAL_NOTIFICATION_ID)
            except Exception:
                self.monitor_error += " Jeśli powiadomienie pracy pozostało, zatrzymaj aplikację w Androidzie."
        finally:
            self.monitor_transition = False
            self.last_scan = await asyncio.to_thread(self.monitor.snapshot)
            self._show_view(self.navigation.selected_index)

    async def _on_lifecycle_change(self, event) -> None:
        if event.state != ft.AppLifecycleState.RESUME or not self.monitor_enabled or self.monitor_transition:
            return
        try:
            if not await self.background.is_enabled():
                await asyncio.to_thread(self.monitor.stop)
                self.monitor_enabled = False
                self.monitor_error = "Praca w tle została zatrzymana. Włącz skanowanie ponownie."
                self._show_view(self.navigation.selected_index)
        except Exception:
            self.monitor_error = "Nie udało się potwierdzić stanu pracy w tle."

    async def _watch_monitor(self) -> None:
        while True:
            try:
                snapshot = await asyncio.to_thread(self.monitor.snapshot)
                signature = json.dumps(snapshot, sort_keys=True)
                if signature != self.monitor_signature:
                    self.monitor_signature = signature
                    self.last_scan = snapshot
                    self.scan_in_progress = snapshot["scanning"]
                    self.scan_error = snapshot["last_error"]
                    if self.navigation.selected_index in (0, 1):
                        self._show_view(self.navigation.selected_index)
                if not self.monitor_transition:
                    await self._sync_proposal_notification(snapshot.get("proposal"))
            except asyncio.CancelledError:
                raise
            except Exception:
                self.monitor_error = "Nie udało się odświeżyć stanu lub powiadomienia. Ponawiam."
            await asyncio.sleep(1)

    async def _sync_proposal_notification(self, proposal: dict | None) -> None:
        now = datetime.now(timezone.utc)
        if now.timestamp() < self.notification_retry_at:
            return
        proposal_id = proposal.get("proposal_id") if proposal and self.monitor_enabled else None
        if proposal_id == self.notified_proposal_id:
            return
        try:
            if not proposal_id:
                await self.notifications.cancel(PROPOSAL_NOTIFICATION_ID)
                self.notified_proposal_id = None
                return
            remaining = (datetime.fromisoformat(proposal["expires_at"]) - now).total_seconds()
            if remaining <= 0:
                return
            signal = proposal.get("signal") or {}
            position = float(proposal.get("position_eurc") or 0)
            costs = position * float(proposal.get("estimated_round_trip_cost_bps") or 0) / 10000
            side = "Kupno" if signal.get("signal") == "BUY_CANDIDATE" else "Sprzedaż"
            await self.notifications.show_notification(
                notification_id=PROPOSAL_NOTIFICATION_ID,
                title=f"NexTrade: {proposal['pair']}",
                body=f"{side} • {position:.2f} EURC • cena {float(signal.get('last_price') or 0):.8g} EURC. "
                     f"Szac. koszty wejścia/wyjścia {costs:.4f} EURC. Otwórz szczegóły.",
                payload=proposal_id,
                actions=[NotificationAction("review", "Zobacz propozycję"),
                         NotificationAction("reject", "Odrzuć", shows_user_interface=True)],
                channel_id="nextrade_proposals_v1", channel_name="Propozycje EURC",
                channel_description="Aktualne propozycje do oceny; bez automatycznego zakupu",
                icon="ic_nextrade_monitor", visibility="private",
                timeout_after=max(1, int(remaining * 1000)),
            )
            current = (await asyncio.to_thread(self.monitor.snapshot)).get("proposal")
            if not self.monitor_enabled or not current or current.get("proposal_id") != proposal_id:
                await self.notifications.cancel(PROPOSAL_NOTIFICATION_ID)
                self.notified_proposal_id = None
                return
            self.notified_proposal_id = proposal_id
        except Exception:
            self.notification_retry_at = now.timestamp() + 30
            self.monitor_error = "Nie udało się wyświetlić alertu. Sprawdź powiadomienia NexTrade w Androidzie."

    async def _on_notification_tap(self, event) -> None:
        try:
            data = json.loads(event.data)
            proposal_id = data.get("payload")
        except (ValueError, TypeError, AttributeError):
            return
        snapshot = await asyncio.to_thread(self.monitor.snapshot)
        proposal = snapshot.get("proposal")
        self.last_scan = snapshot
        self._show_view(1)
        if not proposal or proposal.get("proposal_id") != proposal_id:
            self._show_message("Ta propozycja wygasła lub została zastąpiona. Pokazuję aktualny stan.", WARNING)
            return
        if data.get("action_id") == "reject":
            await self._reject_by_id(proposal_id)
        # Opening an alert is never consent and never invokes an order endpoint.

    def _signals_view(self) -> ft.Control:
        controls: list[ft.Control] = [
            self._section_title(
                "Sygnały",
                "Ranking po jakości rynku, kosztach, ryzyku i historii wyników.",
            ),
            ft.Button(
                "Odśwież sygnały",
                icon=ft.Icons.REFRESH,
                on_click=self._refresh_signals,
                disabled=self.scan_in_progress or self.decision_in_progress,
            ),
        ]

        if self.scan_in_progress:
            controls.append(self._card(ft.Text("Szukam kolejnej okazji…", color=ACCENT)))
        if self.scan_error:
            controls.append(self._card(ft.Text(self.scan_error, color=DANGER)))

        if not self.last_scan:
            controls.append(
                self._card(
                    ft.Text(
                        "Włącz skanowanie w tle na ekranie Start lub odśwież sygnały.",
                        color=MUTED,
                    )
                )
            )
        else:
            proposals = self.last_scan.get("proposals") or []
            if not any(item.get("status") == "PROPOSAL" for item in proposals):
                controls.append(self._card(ft.Text(
                    "Brak propozycji spełniających kryteria w tym skanie. "
                    "Przy włączonym monitorowaniu wyszukiwanie będzie ponawiane automatycznie.",
                    color=MUTED,
                )))
            for index, item in enumerate(proposals):
                if index == 0 and item.get("status") == "PROPOSAL":
                    controls.append(ft.Text(
                        "Najwyżej oceniona propozycja", color=SUCCESS,
                        weight=ft.FontWeight.BOLD,
                    ))
                controls.append(self._signal_card(item))

        rejections = self.core.journal.recent_rejections()
        if rejections:
            controls.append(ft.Text("Ostatnio odrzucone", color=TEXT, weight=ft.FontWeight.BOLD))
            for rejected in rejections:
                controls.append(ft.Text(
                    f"{rejected['pair']} • pomijanie do "
                    f"{self._display_time(rejected['skip_until'])}",
                    color=MUTED, size=12,
                ))
        return self._screen(controls)

    @staticmethod
    def _display_time(value: str) -> str:
        return datetime.fromisoformat(value).astimezone().strftime("%d.%m %H:%M %Z")

    def _markets_view(self) -> ft.Control:
        automatic = self.selected_assets is None
        selection_locked = (self.scan_in_progress or self.decision_in_progress
                            or self.market_selection_in_progress)
        controls = [
            self._section_title("Rynki EURC", "Dostępność bezpośrednich par na Krakenie."),
            ft.Switch(
                label="Wszystkie dostępne pary EURC",
                value=automatic,
                disabled=selection_locked,
                on_change=self._change_market_mode,
            ),
            ft.Text(
                "Tryb automatyczny obejmuje również nowe pary EURC dodane przez Kraken. "
                "Wyłącz go, jeśli chcesz wskazać własną listę. "
                "Wybrane aktywa bez pary EURC czekają na jej dostępność.",
                color=MUTED, size=12,
            ),
            ft.Button(
                "Odśwież dostępność",
                on_click=self._refresh_market_catalog,
                disabled=self.market_refresh_in_progress,
            ),
        ]
        if self.market_refresh_in_progress:
            controls.append(ft.Text("Pobieram listę rynków…", color=ACCENT))
        if self.market_error:
            controls.append(ft.Text(self.market_error, color=DANGER))
        catalog = self.market_catalog or [
            {"symbol": symbol, "name": name, "pair": None, "available": False}
            for symbol, name in WATCHLIST_ASSETS.items()
        ]
        for market in catalog:
            symbol = market["symbol"]
            available = market["available"]
            label = (market["pair"] + " • aktywna para" if available else
                     "Brak aktywnej pary EURC" if self.market_catalog is not None else
                     "Dostępność jeszcze niepotwierdzona")
            controls.append(self._card(ft.Column(
                spacing=2,
                controls=[
                    ft.Checkbox(
                        label=f"{symbol} — {market['name']}",
                        value=available if automatic else symbol in self.selected_assets,
                        data=symbol,
                        disabled=automatic or selection_locked,
                        on_change=self._change_market_selection,
                    ),
                    ft.Text(label, color=SUCCESS if available else MUTED, size=12),
                ],
            )))
        return self._screen(controls)

    async def _refresh_market_catalog(self, _event: ft.Event | None = None) -> None:
        if self.market_refresh_in_progress:
            return
        self.market_refresh_in_progress = True
        self.market_error = None
        try:
            if self.navigation.selected_index == 4:
                self._show_view(4)
            self.market_catalog = await asyncio.to_thread(fetch_market_catalog)
        except Exception:
            self.market_error = "Nie udało się potwierdzić dostępności. Spróbuj odświeżyć listę."
        finally:
            self.market_refresh_in_progress = False
            if self.navigation.selected_index == 4:
                self._show_view(4)

    async def _save_market_selection(self, selection: set[str] | None) -> None:
        if self.scan_in_progress or self.decision_in_progress or self.market_selection_in_progress:
            return
        self.market_selection_in_progress = True
        try:
            self._show_view(4)
            await asyncio.to_thread(self.core.journal.set_market_selection, selection)
            await asyncio.to_thread(self.monitor.invalidate)
            self.selected_assets = selection
            self.last_scan = None
            self.scan_error = None
        except Exception:
            self._show_message("Nie udało się zapisać wyboru rynków. Spróbuj ponownie.", DANGER)
        finally:
            self.market_selection_in_progress = False
            self._show_view(self.navigation.selected_index)

    async def _change_market_mode(self, event: ft.Event) -> None:
        selection = None if event.control.value else {
            item["symbol"] for item in self.market_catalog or [] if item["available"]
        }
        await self._save_market_selection(selection)

    async def _change_market_selection(self, event: ft.Event) -> None:
        if self.selected_assets is None:
            return
        selection = set(self.selected_assets)
        if event.control.value:
            selection.add(event.control.data)
        else:
            selection.discard(event.control.data)
        await self._save_market_selection(selection)

    def _signal_card(self, item: dict[str, Any]) -> ft.Control:
        status = str(item.get("status") or "WAIT")
        signal = item.get("signal") or {}
        opportunity = item.get("opportunity") or {}
        confidence = float(signal.get("confidence") or 0.0)
        position = float(item.get("position_eurc") or 0.0)
        score = float(item.get("final_score") or 0.0)
        spread = float(opportunity.get("spread_bps") or 0.0)
        reason = str(item.get("reason") or "")

        status_color = {
            "PROPOSAL": SUCCESS,
            "WAIT": WARNING,
            "FILTERED": MUTED,
            "SKIPPED": DANGER,
        }.get(status, MUTED)

        rows: list[ft.Control] = [
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Text(
                        str(item.get("pair") or "—"),
                        size=18,
                        weight=ft.FontWeight.BOLD,
                        color=TEXT,
                    ),
                    ft.Text(status, color=status_color, weight=ft.FontWeight.BOLD),
                ],
            ),
            ft.Text(
                f"{signal.get('signal', 'N/A')} • ocena sygnału {confidence:.0f}/100",
                color=MUTED,
            ),
            ft.Text(
                f"Pozycja EURC {position:.2f} • score {score:.2f} • spread {spread:.1f} bps",
                color=MUTED,
                size=12,
            ),
        ]
        if reason:
            rows.append(ft.Text(f"Filtr: {reason}", color=WARNING, size=12))

        if status == "PROPOSAL":
            entry = float(signal.get("last_price") or 0.0)
            costs_bps = float(item.get("estimated_round_trip_cost_bps") or 0.0)
            rows.append(ft.Text(
                f"Cena odniesienia EURC {entry:.8g} • szacowane koszty wejścia "
                f"i wyjścia EURC {position * costs_bps / 10_000:.4f}",
                color=MUTED, size=12,
            ))
            intent = item.get("trade_intent")
            if intent:
                rows.extend([
                    ft.Text(
                        f"Plan zakupu: {intent['order_volume']} jednostek po maks. {intent['order_limit_price']} EURC. "
                        f"Kwota do {intent['position_eurc']:.2f} EURC plus do "
                        f"{intent['entry_fee_allowance_eurc']:.4f} EURC prowizji wejścia.",
                        color=TEXT, size=12,
                    ),
                    ft.Text(
                        f"Plan wyjścia: cel {intent['order_take_profit']} EURC • "
                        f"próg stop {intent['order_stop_trigger']} EURC.",
                        color=TEXT, size=12,
                    ),
                    ft.Text(
                        f"Szacunek po kosztach: przy celu {intent['estimated_target_pnl_eurc']:+.4f} EURC; "
                        f"przy cenie stop {intent['estimated_stop_pnl_eurc']:+.4f} EURC. "
                        "Cena wykonania stop może być gorsza. To plan, zlecenia są wyłączone.",
                        color=MUTED, size=12,
                    ),
                ])
            if item.get("analyzed_at"):
                rows.append(ft.Text(
                    f"Analiza rozpoczęta: {self._display_time(item['analyzed_at'])}",
                    color=MUTED, size=12,
                ))
            if item.get("expires_at"):
                rows.append(ft.Text(
                    f"Ważna do: {self._display_time(item['expires_at'])}",
                    color=WARNING, size=12,
                ))
            rows.append(ft.Row(
                wrap=True,
                controls=[
                    ft.Button("Inwestuj", disabled=True),
                    ft.Button(
                        "Odrzuć",
                        icon=ft.Icons.CLOSE,
                        data=item.get("proposal_id"),
                        on_click=self._reject_proposal,
                        disabled=(self.decision_in_progress
                                  or not item.get("proposal_id")),
                    ),
                ],
            ))
            rows.append(ft.Text(
                "Inwestuj jest wyłączone w tej wersji. Odrzuć zapisuje decyzję "
                "i od razu szuka kolejnej okazji.",
                color=MUTED, size=12,
            ))

        return self._card(ft.Column(spacing=7, controls=rows), border_color=status_color)

    def _portfolio_view(self) -> ft.Control:
        controls: list[ft.Control] = [
            self._section_title(
                "Portfel",
                "Saldo Kraken i orientacyjna wycena portfela w EURC.",
            ),
            ft.Button(
                "Odśwież portfel",
                icon=ft.Icons.REFRESH,
                on_click=self._refresh_portfolio,
                disabled=not self.credentials_configured,
            ),
        ]

        if not self.credentials_configured:
            controls.append(
                self._card(
                    ft.Column(
                        spacing=8,
                        controls=[
                            ft.Icon(ft.Icons.LOCK_OUTLINE, color=WARNING),
                            ft.Text("Najpierw zapisz klucze Kraken w Ustawieniach.", color=TEXT),
                            ft.Text(
                                "Użyj osobnego klucza tylko z odczytem i handlem. Nigdy nie włączaj wypłat.",
                                color=MUTED,
                                size=12,
                            ),
                        ],
                    )
                )
            )
            return self._screen(controls)

        if not self.portfolio_snapshot:
            controls.append(
                self._card(
                    ft.Text(
                        "Klucze są zapisane. Naciśnij „Odśwież portfel”, aby sprawdzić połączenie.",
                        color=MUTED,
                    )
                )
            )
            return self._screen(controls)

        total = float(self.portfolio_snapshot.get("total_eurc") or 0.0)
        unpriced = self.portfolio_snapshot.get("unpriced") or []
        controls.append(
            self._card(
                ft.Column(
                    spacing=3,
                    controls=[
                        ft.Text(
                            "Częściowa wycena" if unpriced else "Łączna wycena",
                            color=MUTED,
                        ),
                        ft.Text(
                            f"EURC {total:,.2f}",
                            size=30,
                            weight=ft.FontWeight.BOLD,
                            color=TEXT,
                        ),
                    ],
                ),
                border_color=SUCCESS,
            )
        )

        if unpriced:
            controls.append(
                self._card(
                    ft.Column(
                        spacing=6,
                        controls=[
                            ft.Text(
                                "Nie wszystkie aktywa mają wycenę w EURC.",
                                color=WARNING,
                                weight=ft.FontWeight.BOLD,
                            ),
                            ft.Text(
                                "Poniższe salda nie są uwzględnione w podanej sumie.",
                                color=MUTED,
                                size=12,
                            ),
                            *[
                                ft.Text(
                                    f"{item.get('asset', '—')}: "
                                    f"{float(item.get('amount') or 0.0):.8g} • brak wyceny",
                                    color=MUTED,
                                )
                                for item in unpriced
                            ],
                        ],
                    ),
                    border_color=WARNING,
                )
            )

        for holding in self.portfolio_snapshot.get("holdings") or []:
            controls.append(
                self._card(
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(
                                spacing=2,
                                controls=[
                                    ft.Text(str(holding.get("asset") or "—"), color=TEXT),
                                    ft.Text(
                                        f"{float(holding.get('amount') or 0.0):.8g}",
                                        color=MUTED,
                                        size=12,
                                    ),
                                ],
                            ),
                            ft.Text(
                                f"EURC {float(holding.get('value_eurc') or 0.0):,.2f}",
                                color=TEXT,
                                weight=ft.FontWeight.BOLD,
                            ),
                        ],
                    )
                )
            )
        return self._screen(controls)

    def _settings_view(self) -> ft.Control:
        security_note = self._card(
            ft.Column(
                spacing=7,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.SECURITY, color=SUCCESS),
                            ft.Text("Android Keystore", color=TEXT, weight=ft.FontWeight.BOLD),
                        ]
                    ),
                    self.credentials_status,
                    ft.Text(
                        "Klucze są szyfrowane na urządzeniu. Aplikacja nie pokazuje zapisanej wartości i nie zapisuje jej w repozytorium ani dzienniku.",
                        color=MUTED,
                        size=12,
                    ),
                ],
            ),
            border_color=SUCCESS if self.credentials_configured else WARNING,
        )

        return self._screen(
            [
                self._section_title(
                    "Ustawienia",
                    "Bezpieczne połączenie aplikacji z Krakenem.",
                ),
                self._monitor_card(),
                self._card(ft.Column(
                    spacing=8,
                    controls=[
                        ft.Text("Odrzucanie propozycji", color=TEXT, weight=ft.FontWeight.BOLD),
                        self.rejection_cooldown_field,
                        ft.Button("Zapisz czas pomijania", on_click=self._save_rejection_settings),
                    ],
                )),
                security_note,
                self.api_key_field,
                self.api_secret_field,
                ft.Text(
                    "W Krakenie utwórz osobny klucz bez uprawnienia do wypłat.",
                    color=WARNING,
                    size=12,
                ),
                ft.Row(
                    wrap=True,
                    spacing=10,
                    controls=[
                        ft.Button(
                            "Zapisz klucze",
                            icon=ft.Icons.SAVE,
                            on_click=self._save_credentials,
                        ),
                        ft.Button(
                            "Usuń klucze",
                            icon=ft.Icons.DELETE_OUTLINE,
                            on_click=self._remove_credentials,
                        ),
                    ],
                ),
                self._card(
                    ft.Column(
                        spacing=6,
                        controls=[
                            ft.Text("Tryb zleceń", color=TEXT, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "WYŁĄCZONY — aktualna wersja analizuje rynek i portfel, ale nie wysyła prawdziwych zleceń.",
                                color=MUTED,
                                size=12,
                            ),
                        ],
                    ),
                    border_color=WARNING,
                ),
            ]
        )

    async def _save_rejection_settings(self, _event: ft.Event | None = None) -> None:
        try:
            minutes = int(self.rejection_cooldown_field.value or "")
            await asyncio.to_thread(self.core.journal.set_rejection_cooldown_minutes, minutes)
            self._show_message(f"Kolejne odrzucone pary będą pomijane przez {minutes} min.", SUCCESS)
        except (TypeError, ValueError):
            self._show_message("Wpisz liczbę pełnych minut od 1 do 1440.", WARNING)
        except Exception:
            self._show_message("Nie udało się zapisać czasu pomijania. Spróbuj ponownie.", DANGER)

    async def _reject_proposal(self, event: ft.Event) -> None:
        await self._reject_by_id(event.control.data)

    async def _reject_by_id(self, proposal_id: str) -> None:
        if self.decision_in_progress or self.market_selection_in_progress:
            return
        self.decision_in_progress = True
        saved = False
        try:
            self._show_view(self.navigation.selected_index)
            saved = await asyncio.to_thread(self.monitor.reject, proposal_id)
            self.last_scan = await asyncio.to_thread(self.monitor.snapshot)
            if saved:
                self._show_message("Odrzucenie zapisane. Szukam kolejnej okazji.", SUCCESS)
            else:
                self._show_message("Ta propozycja wygasła, została zastąpiona lub odrzucona.", WARNING)
        except Exception:
            self._show_message("Nie udało się zapisać odrzucenia. Spróbuj ponownie.", DANGER)
        finally:
            self.decision_in_progress = False
            self._show_view(self.navigation.selected_index)
        if saved and not self.monitor_enabled:
            await self._refresh_signals()

    async def _refresh_signals(self, _event: ft.Event | None = None) -> None:
        if self.scan_in_progress or self.decision_in_progress or self.market_selection_in_progress:
            return
        self.scan_in_progress = True
        self.scan_error = None
        try:
            self._show_view(self.navigation.selected_index)
            self._show_busy("Skanuję rynki EURC…")
            await asyncio.to_thread(self.monitor.scan_once)
            self.last_scan = await asyncio.to_thread(self.monitor.snapshot)
            self.scan_error = self.last_scan.get("last_error")
            self.navigation.selected_index = 1
            self._show_view(1)
        except Exception as error:
            self.scan_error = (
                f"Skanowanie nie powiodło się: {error}. "
                "Odrzucenia pozostają zapisane. Spróbuj odświeżyć sygnały."
            )
            self._show_message(self.scan_error, DANGER)
        finally:
            self.scan_in_progress = False
            self._show_view(self.navigation.selected_index)

    async def _refresh_credentials_status(self) -> None:
        try:
            has_key, has_secret = await asyncio.gather(
                self.storage.contains_key(KRAKEN_API_KEY),
                self.storage.contains_key(KRAKEN_PRIVATE_KEY),
            )
            self.credentials_configured = bool(has_key and has_secret)
            self.credentials_status.value = (
                "Klucze Kraken są zapisane."
                if self.credentials_configured
                else "Klucze Kraken nie są jeszcze zapisane."
            )
            self.credentials_status.color = (
                SUCCESS if self.credentials_configured else WARNING
            )
            self.page.update()
        except Exception as error:
            self.credentials_configured = False
            self.credentials_status.value = f"Magazyn niedostępny: {error}"
            self.credentials_status.color = DANGER
            self.page.update()

    async def _save_credentials(self, _event: ft.Event | None = None) -> None:
        api_key = (self.api_key_field.value or "").strip()
        private_key = (self.api_secret_field.value or "").strip()
        if not api_key or not private_key:
            self._show_message("Wpisz oba klucze Kraken.", WARNING)
            return

        try:
            await self.storage.set(KRAKEN_API_KEY, api_key)
            await self.storage.set(KRAKEN_PRIVATE_KEY, private_key)
            self.api_key_field.value = ""
            self.api_secret_field.value = ""
            await self._refresh_credentials_status()
            self._show_message("Klucze zapisane w Android Keystore.", SUCCESS)
            self._show_view(3)
        except Exception as error:
            self._show_message(f"Nie udało się zapisać kluczy: {error}", DANGER)

    async def _remove_credentials(self, _event: ft.Event | None = None) -> None:
        try:
            await asyncio.gather(
                self.storage.remove(KRAKEN_API_KEY),
                self.storage.remove(KRAKEN_PRIVATE_KEY),
            )
            self.portfolio_snapshot = None
            await self._refresh_credentials_status()
            self._show_message("Klucze usunięte z urządzenia.", SUCCESS)
            self._show_view(3)
        except Exception as error:
            self._show_message(f"Nie udało się usunąć kluczy: {error}", DANGER)

    async def _refresh_portfolio(self, _event: ft.Event | None = None) -> None:
        self._show_busy("Pobieram saldo Kraken…")
        try:
            api_key, private_key = await asyncio.gather(
                self.storage.get(KRAKEN_API_KEY),
                self.storage.get(KRAKEN_PRIVATE_KEY),
            )
            if not api_key or not private_key:
                self.credentials_configured = False
                self._show_message("Brak zapisanych kluczy Kraken.", WARNING)
                self._show_view(3)
                return

            client = KrakenClient(key=api_key, secret=private_key)
            self.portfolio_snapshot = await asyncio.to_thread(
                fetch_portfolio_eurc,
                client,
            )
            self.navigation.selected_index = 2
            self._show_view(2)
        except Exception as error:
            self._show_message(f"Nie udało się pobrać portfela: {error}", DANGER)

    def _show_busy(self, message: str) -> None:
        self.page.show_dialog(
            ft.SnackBar(
                content=ft.Row(
                    controls=[
                        ft.ProgressRing(width=20, height=20, stroke_width=2),
                        ft.Text(message),
                    ]
                )
            )
        )

    def _show_message(self, message: str, color: str = ACCENT) -> None:
        self.page.show_dialog(
            ft.SnackBar(
                bgcolor=color,
                content=ft.Text(message, color="#071021"),
            )
        )


def main(page: ft.Page) -> None:
    NexTradeAndroidApp(page)


if __name__ == "__main__":
    ft.run(main)
