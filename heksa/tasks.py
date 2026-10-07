"""Persistent local tasks. Interrupted work requires explicit review, never auto-replay."""
import sqlite3
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone


class TaskQueue:
    def __init__(self, path):
        self.path = Path(path)
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, agent TEXT NOT NULL, action TEXT NOT NULL,
                state TEXT NOT NULL, created TEXT NOT NULL, result TEXT,
                CHECK(state IN ('pending','running','completed','failed','cancelled','interrupted'))
            )''')

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def add(self, agent, action):
        task_id = uuid4().hex
        with self._connect() as db:
            db.execute('INSERT INTO tasks VALUES (?, ?, ?, ?, ?, NULL)',
                       (task_id, agent, action, 'pending', datetime.now(timezone.utc).isoformat()))
        return task_id

    def list(self):
        with self._connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM tasks ORDER BY created, id')]

    def claim(self):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM tasks WHERE state='pending' ORDER BY created, id LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE tasks SET state='running' WHERE id=?", (row['id'],))
            return dict(row)

    def finish(self, task_id, state, result):
        if state not in {'completed', 'failed'}:
            raise ValueError('Invalid final state')
        with self._connect() as db:
            changed = db.execute("UPDATE tasks SET state=?, result=? WHERE id=? AND state='running'",
                                 (state, str(result), task_id)).rowcount
            if changed != 1:
                raise ValueError('Task is not running')

    def cancel(self, task_id):
        with self._connect() as db:
            return db.execute("UPDATE tasks SET state='cancelled' WHERE id=? AND state='pending'",
                              (task_id,)).rowcount == 1

    def interrupt_running(self):
        """Call only after verifying that the previous worker has stopped."""
        with self._connect() as db:
            return db.execute("UPDATE tasks SET state='interrupted' WHERE state='running'").rowcount
