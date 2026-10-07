"""Local agent coordinator. No external services or arbitrary code execution."""
import json
from datetime import datetime, timezone
from pathlib import Path
from .tasks import TaskQueue
from . import __version__

class SecurityAgent:
    """Allow only explicitly registered local capabilities."""
    def __init__(self):
        self._allowed = {"system": frozenset({"status", "time"})}

    def authorize(self, agent, action):
        if action not in self._allowed.get(agent, ()):
            raise PermissionError("Security Agent: działanie niedozwolone.")

class SystemAgent:
    name = "system"
    def run(self, action):
        if action == "status":
            return f"Heksa Core {__version__} online. Tryb lokalny."
        if action == "time":
            return datetime.now().astimezone().isoformat(timespec="seconds")
        raise ValueError("Nieznana akcja.")

class HeksaCore:
    def __init__(self, data_dir=None):
        self.security = SecurityAgent()
        self._agents = {"system": SystemAgent()}
        self.data_dir = Path(data_dir) if data_dir is not None else Path.home() / ".heksa"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tasks = TaskQueue(self.data_dir / "tasks.sqlite3")

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
            "agent": agent, "action": action, "outcome": outcome,
        }
        with (self.data_dir / "audit.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def dispatch(self, agent, action):
        try:
            self.security.authorize(agent, action)
        except PermissionError:
            self._audit(agent, action, "blocked")
            raise
        # Audit must succeed before an agent can execute.
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
            if len(parts) != 2 or parts[1] not in {"status", "time"}:
                return "Użycie: queue status lub queue time"
            return "Dodano zadanie: " + self.queue_task("system", parts[1])
        if normalized == "tasks":
            tasks = self.tasks.list()
            return "\n".join(f"{t['id']} {t['agent']}/{t['action']}: {t['state']}" for t in tasks) or "Brak zadań."
        if normalized == "run-next":
            return self.run_next_task()
        if parts and parts[0] == "cancel":
            if len(parts) != 2:
                return "Użycie: cancel <id>"
            return "Anulowano zadanie." if self.tasks.cancel(parts[1]) else "Nie ma oczekującego zadania o tym ID."
        if normalized in {"status", "time"}:
            return self.dispatch("system", normalized)
        if normalized in {"hello", "hej"}:
            return "Witaj, szefie. Heksa gotowa do lokalnego testu."
        if normalized in {"help", "pomoc"}:
            return "Komendy: status, time, hello, agents, queue status|time, tasks, run-next, cancel <id>, help, exit"
        if normalized == "agents":
            return "Security Agent: aktywny; System Agent: aktywny. Pozostałe integracje: niewdrożone."
        return "Nieznana komenda. Wpisz help."
