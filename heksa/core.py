"""Agent coordinator for local market, portfolio and performance capabilities."""
import json
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .journal import SignalJournal
from .pair_scanner import best_eur_pairs
from .portfolio import fetch_portfolio_eur
from .tasks import TaskQueue
from .trading_runner import build_best_eur_proposals


class SecurityAgent:
    """Allow only explicitly registered capabilities."""

    def __init__(self):
        self._allowed = {
            "system": frozenset({"status", "time"}),
            "market": frozenset({"eur_pairs", "signals"}),
            "portfolio": frozenset({"eur_value"}),
            "performance": frozenset({"summary", "history", "close"}),
        }

    def authorize(self, agent, action):
        if action not in self._allowed.get(agent, ()):
            raise PermissionError("Security Agent: działanie niedozwolone.")


class SystemAgent:
    name = "system"

    def run(self, action):
        if action == "status":
            return f"Heksa Core {__version__} online."
        if action == "time":
            return datetime.now().astimezone().isoformat(timespec="seconds")
        raise ValueError("Nieznana akcja.")


class MarketAgent:
    name = "market"

    def __init__(self, journal: SignalJournal):
        self.journal = journal

    def run(self, action):
        if action == "eur_pairs":
            pairs = best_eur_pairs(limit=5)
            if not pairs:
                return "Brak par EUR spełniających aktualne filtry."

            rows = []
            for index, item in enumerate(pairs, start=1):
                rows.append(
                    f"{index}. {item['pair']} | "
                    f"score {item['opportunity_score']:.2f} | "
                    f"24h {item['range_24h_pct']:.2f}% | "
                    f"spread {item['spread_bps']:.1f} bps | "
                    f"vol €{item['quote_volume_24h_eur']:.0f}"
                )
            return "\n".join(rows)

        if action == "signals":
            result = build_best_eur_proposals(limit=5)
            rows = []
            for index, item in enumerate(result["proposals"], start=1):
                journal_id = self.journal.record(item)
                signal = item.get("signal") or {}
                rows.append(
                    f"{index}. {item['pair']} | {item['status']} | "
                    f"{signal.get('signal', 'N/A')} | "
                    f"conf {float(signal.get('confidence', 0.0)):.0f}% | "
                    f"€{float(item.get('position_eur', 0.0)):.2f} | "
                    f"score {float(item.get('final_score', 0.0)):.2f} | "
                    f"id {journal_id[:8]}"
                )
            return "\n".join(rows) if rows else "Brak kandydatów."

        raise ValueError("Nieznana akcja rynku.")


class PortfolioAgent:
    name = "portfolio"

    def run(self, action):
        if action != "eur_value":
            raise ValueError("Nieznana akcja portfela.")

        snapshot = fetch_portfolio_eur()
        lines = [f"Portfel: €{snapshot['total_eur']:.2f}"]
        for item in snapshot["holdings"][:10]:
            lines.append(
                f"{item['asset']}: {item['amount']:.8g} | €{item['value_eur']:.2f}"
            )
        if snapshot["unpriced"]:
            lines.append(f"Bez wyceny EUR: {len(snapshot['unpriced'])}")
        return "\n".join(lines)


class PerformanceAgent:
    name = "performance"

    def __init__(self, journal: SignalJournal):
        self.journal = journal

    def run(self, action):
        if action == "summary":
            data = self.journal.summary()
            return (
                f"Zamknięte: {data['closed_count']} | "
                f"wygrane: {data['wins']} | "
                f"przegrane: {data['losses']} | "
                f"skuteczność {data['win_rate_pct']:.1f}% | "
                f"P&L €{data['pnl_eur']:.2f}"
            )

        if action == "history":
            items = self.journal.recent(limit=10)
            if not items:
                return "Dziennik sygnałów jest pusty."

            rows = []
            for item in items:
                pnl = item.get("pnl_eur")
                pnl_text = f" | P&L €{float(pnl):.2f}" if pnl is not None else ""
                rows.append(
                    f"{item['created']} | {item['pair']} | {item['status']} | "
                    f"conf {float(item.get('confidence') or 0.0):.0f}%"
                    f"{pnl_text}"
                )
            return "\n".join(rows)

        raise ValueError("Nieznana akcja wyników.")


class HeksaCore:
    def __init__(self, data_dir=None):
        self.security = SecurityAgent()
        self.data_dir = Path(data_dir) if data_dir is not None else Path.home() / ".heksa"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tasks = TaskQueue(self.data_dir / "tasks.sqlite3")
        self.journal = SignalJournal(self.data_dir / "signals.sqlite3")
        self._agents = {
            "system": SystemAgent(),
            "market": MarketAgent(self.journal),
            "portfolio": PortfolioAgent(),
            "performance": PerformanceAgent(self.journal),
        }

    def queue_task(self, agent, action):
        try:
            self.security.authorize(agent, action)
        except PermissionError:
            self._audit(agent, action, "blocked")
            raise
        self._audit(agent, action, "queue_authorized")
        return self.tasks.add(agent, action)

    def run_next_task(self):
        task = self.tasks.claim()
        if task is None:
            return "Brak oczekujących zadań."
        try:
            result = self.dispatch(task["agent"], task["action"])
        except Exception as error:
            self.tasks.finish(task["id"], "failed", str(error))
            raise
        self.tasks.finish(task["id"], "completed", result)
        return result

    def _audit(self, agent, action, outcome):
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "action": action,
            "outcome": outcome,
        }
        with (self.data_dir / "audit.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def record_outcome(self, signal_id, exit_eur):
        try:
            self.security.authorize("performance", "close")
        except PermissionError:
            self._audit("performance", "close", "blocked")
            raise
        self._audit("performance", "close", "authorized")
        result = self.journal.close(signal_id, float(exit_eur))
        self._audit("performance", "close", "completed")
        return (
            f"{result['signal_id'][:8]} | {result['result']} | "
            f"P&L €{result['pnl_eur']:.2f}"
        )

    def dispatch(self, agent, action):
        try:
            self.security.authorize(agent, action)
        except PermissionError:
            self._audit(agent, action, "blocked")
            raise

        self._audit(agent, action, "authorized")
        try:
            result = self._agents[agent].run(action)
        except Exception:
            self._audit(agent, action, "failed")
            raise
        self._audit(agent, action, "completed")
        return result

    def process(self, command):
        normalized = command.strip().lower()
        parts = normalized.split()

        if parts and parts[0] == "queue":
            if len(parts) == 2 and parts[1] in {"status", "time"}:
                return "Dodano zadanie: " + self.queue_task("system", parts[1])
            if len(parts) == 2 and parts[1] in {"markets", "pairs"}:
                return "Dodano zadanie: " + self.queue_task("market", "eur_pairs")
            return "Użycie: queue status | queue time | queue markets"

        if normalized == "tasks":
            tasks = self.tasks.list()
            return "\n".join(
                f"{t['id']} {t['agent']}/{t['action']}: {t['state']}" for t in tasks
            ) or "Brak zadań."

        if normalized == "run-next":
            return self.run_next_task()

        if parts and parts[0] == "close":
            if len(parts) != 3:
                return "Użycie: close <pełne_id_sygnalu> <cena_wyjścia_EUR>"
            try:
                return self.record_outcome(parts[1], float(parts[2].replace(",", ".")))
            except ValueError as error:
                return f"Nie można zamknąć wpisu: {error}"

        if parts and parts[0] == "cancel":
            if len(parts) != 2:
                return "Użycie: cancel <id>"
            return (
                "Anulowano zadanie."
                if self.tasks.cancel(parts[1])
                else "Nie ma oczekującego zadania o tym ID."
            )

        if normalized in {"status", "time"}:
            return self.dispatch("system", normalized)

        if normalized in {"markets", "pairs", "eur", "best"}:
            return self.dispatch("market", "eur_pairs")

        if normalized in {"signals", "sygnaly", "sygnały", "candidates"}:
            return self.dispatch("market", "signals")

        if normalized in {"portfolio", "portfel", "balance", "saldo"}:
            return self.dispatch("portfolio", "eur_value")

        if normalized in {"pnl", "performance", "wyniki"}:
            return self.dispatch("performance", "summary")

        if normalized in {"history", "historia", "journal", "dziennik"}:
            return self.dispatch("performance", "history")

        if normalized in {"hello", "hej"}:
            return "Witaj, szefie. Heksa gotowa."

        if normalized in {"help", "pomoc"}:
            return (
                "Komendy: status, time, markets, signals, portfolio, pnl, history, close, "
                "hello, agents, queue status|time|markets, tasks, run-next, "
                "cancel <id>, help, exit"
            )

        if normalized == "agents":
            return (
                "Security Agent: aktywny; System Agent: aktywny; "
                "Market Agent: aktywny; Portfolio Agent: aktywny; "
                "Performance Agent: aktywny."
            )

        return "Nieznana komenda. Wpisz help."
