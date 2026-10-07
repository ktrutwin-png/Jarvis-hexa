"""Local agent coordinator. No external services or arbitrary code execution."""
import json
from datetime import datetime, timezone
from pathlib import Path

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
            return "Heksa Core 0.1.0 online. Tryb lokalny."
        if action == "time":
            return datetime.now().astimezone().isoformat(timespec="seconds")
        raise ValueError("Nieznana akcja.")

class HeksaCore:
    def __init__(self, data_dir=None):
        self.security = SecurityAgent()
        self._agents = {"system": SystemAgent()}
        self.data_dir = Path(data_dir) if data_dir is not None else Path.home() / ".heksa"
        self.data_dir.mkdir(parents=True, exist_ok=True)

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
        if normalized in {"status", "time"}:
            return self.dispatch("system", normalized)
        if normalized in {"hello", "hej"}:
            return "Witaj, szefie. Heksa gotowa do lokalnego testu."
        if normalized in {"help", "pomoc"}:
            return "Komendy: status, time, hello, agents, help, exit"
        if normalized == "agents":
            return "Security Agent: aktywny; System Agent: aktywny. Pozostałe integracje: niewdrożone."
        return "Nieznana komenda. Wpisz help."
