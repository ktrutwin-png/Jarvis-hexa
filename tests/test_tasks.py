import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from heksa.core import HeksaCore
from heksa.tasks import TaskQueue


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.core = HeksaCore(self.folder.name)

    def test_restart_retains_and_executes_task(self):
        task_id = self.core.queue_task('system', 'status')
        restarted = HeksaCore(self.folder.name)
        self.assertEqual(restarted.tasks.list()[0]['id'], task_id)
        self.assertIn('online', restarted.run_next_task())
        self.assertEqual(restarted.tasks.list()[0]['state'], 'completed')
        self.assertEqual(restarted.run_next_task(), 'Brak oczekujących zadań.')

    def test_permission_rechecked_at_execution(self):
        self.core.queue_task('system', 'status')
        self.core.security._allowed = {}
        with self.assertRaises(PermissionError):
            self.core.run_next_task()
        self.assertEqual(self.core.tasks.list()[0]['state'], 'failed')

    def test_unauthorized_task_not_saved(self):
        with self.assertRaises(PermissionError):
            self.core.queue_task('crypto', 'trade')
        self.assertEqual(self.core.tasks.list(), [])

    def test_cancel_prevents_execution(self):
        task_id = self.core.queue_task('system', 'time')
        self.assertTrue(self.core.tasks.cancel(task_id))
        self.assertFalse(self.core.tasks.cancel(task_id))
        self.assertIsNone(self.core.tasks.claim())

    def test_concurrent_claim_is_unique(self):
        self.core.queue_task('system', 'status')
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = list(pool.map(lambda _: self.core.tasks.claim(), range(4)))
        self.assertEqual(sum(task is not None for task in claims), 1)

    def test_interrupted_task_not_replayed_on_restart(self):
        self.core.queue_task('system', 'status')
        self.core.tasks.claim()
        restarted = HeksaCore(self.folder.name)
        self.assertIsNone(restarted.tasks.claim())
        self.assertEqual(restarted.tasks.list()[0]['state'], 'running')
        self.assertEqual(restarted.tasks.interrupt_running(), 1)
        self.assertEqual(restarted.tasks.list()[0]['state'], 'interrupted')

    def test_audit_failure_prevents_queue_and_execution(self):
        (Path(self.folder.name) / 'audit.jsonl').mkdir()
        with self.assertRaises(OSError):
            self.core.queue_task('system', 'status')
        self.assertEqual(self.core.tasks.list(), [])
        self.core.tasks.add('system', 'status')
        class Spy:
            def run(self, action):
                raise AssertionError('Agent ran without audit')
        self.core._agents['system'] = Spy()
        with self.assertRaises(OSError):
            self.core.run_next_task()
        self.assertEqual(self.core.tasks.list()[0]['state'], 'failed')

    def test_cli_queue_flow(self):
        response = self.core.process('queue time')
        task_id = response.split()[-1]
        self.assertIn('pending', self.core.process('tasks'))
        self.assertEqual(self.core.process('cancel ' + task_id), 'Anulowano zadanie.')
        self.assertIn('cancelled', self.core.process('tasks'))


if __name__ == '__main__':
    unittest.main()
