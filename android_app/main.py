"""NexTrade Android entry point.

The first mobile shell exposes read-only market scanning, portfolio valuation
and encrypted Kraken credential storage. Live order submission is deliberately
not enabled.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import flet as ft
import flet_secure_storage as fss

from heksa.core import HeksaCore
from heksa.kraken import KrakenClient
from heksa.portfolio import fetch_portfolio_eur
from heksa.trading_runner import build_best_eur_proposals


APP_NAME = "NexTrade"
APP_VERSION = "0.1.0"
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
        self.last_scan: dict[str, Any] | None = None
        self.portfolio_snapshot: dict[str, Any] | None = None
        self.credentials_configured = False
        self.scan_in_progress = False

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
            ],
        )

        self._configure_page()
        self._show_view(0)
        self.page.run_task(self._refresh_credentials_status)

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
                self._metric("Waluta", "EUR"),
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
                ft.Button(
                    "Skanuj rynek EUR",
                    icon=ft.Icons.REFRESH,
                    on_click=self._refresh_signals,
                    disabled=self.scan_in_progress,
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
                disabled=self.scan_in_progress,
            ),
        ]

        if not self.last_scan:
            controls.append(
                self._card(
                    ft.Text(
                        "Nie wykonano jeszcze skanowania. Naciśnij „Odśwież sygnały”.",
                        color=MUTED,
                    )
                )
            )
            return self._screen(controls)

        proposals = self.last_scan.get("proposals") or []
        if not proposals:
            controls.append(self._card(ft.Text("Brak kandydatów.", color=MUTED)))
            return self._screen(controls)

        for item in proposals:
            controls.append(self._signal_card(item))
        return self._screen(controls)

    def _signal_card(self, item: dict[str, Any]) -> ft.Control:
        status = str(item.get("status") or "WAIT")
        signal = item.get("signal") or {}
        opportunity = item.get("opportunity") or {}
        confidence = float(signal.get("confidence") or 0.0)
        position = float(item.get("position_eur") or 0.0)
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
                f"{signal.get('signal', 'N/A')} • pewność {confidence:.0f}%",
                color=MUTED,
            ),
            ft.Text(
                f"Pozycja €{position:.2f} • score {score:.2f} • spread {spread:.1f} bps",
                color=MUTED,
                size=12,
            ),
        ]
        if reason:
            rows.append(ft.Text(f"Filtr: {reason}", color=WARNING, size=12))

        return self._card(ft.Column(spacing=7, controls=rows), border_color=status_color)

    def _portfolio_view(self) -> ft.Control:
        controls: list[ft.Control] = [
            self._section_title(
                "Portfel",
                "Odczyt salda Kraken i wycena w EUR. Bez prawa do wypłat.",
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

        total = float(self.portfolio_snapshot.get("total_eur") or 0.0)
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
                            f"€{total:,.2f}",
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
                                "Nie wszystkie aktywa mają wycenę w EUR.",
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
                                f"€{float(holding.get('value_eur') or 0.0):,.2f}",
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

    async def _refresh_signals(self, _event: ft.Event | None = None) -> None:
        if self.scan_in_progress:
            return
        self.scan_in_progress = True
        try:
            self._show_view(self.navigation.selected_index)
            self._show_busy("Skanuję rynki EUR…")
            result = await asyncio.to_thread(
                lambda: build_best_eur_proposals(
                    limit=5,
                    journal=self.core.journal,
                )
            )
            self.last_scan = result
            self.navigation.selected_index = 1
            self._show_view(1)
        except Exception as error:
            self._show_message(f"Skanowanie nie powiodło się: {error}", DANGER)
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
                fetch_portfolio_eur,
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
