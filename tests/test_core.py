import json
import tempfile
import unittest
from pathlib import Path
from heksa.core import HeksaCore

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.core = HeksaCore(self.folder.name)

    def test_status_and_audit(self):
        self.assertIn("online", self.core.process(" STATUS "))
        events = [json.loads(line) for line in
                  (Path(self.folder.name) / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([e["outcome"] for e in events], ["authorized", "completed"])

    def test_unregistered_agent_never_runs(self):
        class Spy:
            def run(self, action):
                raise AssertionError("Unauthorized agent ran")
        self.core._agents["crypto"] = Spy()
        with self.assertRaises(PermissionError):
            self.core.dispatch("crypto", "trade")
        event = json.loads((Path(self.folder.name) / "audit.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(event["outcome"], "blocked")

    def test_unknown_action_blocked(self):
        with self.assertRaises(PermissionError):
            self.core.dispatch("system", "execute")
        self.assertIn("Nieznana", self.core.process("send money"))

    def test_audit_failure_prevents_execution(self):
        class Spy:
            def run(self, action):
                raise AssertionError("Agent ran without audit")
        self.core._agents["system"] = Spy()
        (Path(self.folder.name) / "audit.jsonl").mkdir()
        with self.assertRaises(OSError):
            self.core.dispatch("system", "status")

    def test_restart_retains_audit(self):
        self.core.process("status")
        HeksaCore(self.folder.name).process("time")
        self.assertEqual(len((Path(self.folder.name) / "audit.jsonl").read_text().splitlines()), 4)

if __name__ == "__main__":
    unittest.main()
