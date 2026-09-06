"""Synchronous LangGraph saver over the existing tenant-local SQL connection.

Only server-generated thread IDs are accepted. No public checkpoint, time-travel,
subgraph or arbitrary-state update API. Graph state contains data, never clients,
secrets or callable tools. SQL transactions are short; no network I/O under a lock.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
import time
import uuid

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, WRITES_IDX_MAP
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from retailops.core import require


class SqlSaver(BaseCheckpointSaver):
    def __init__(self, store, customer, run_id, owner):
        super().__init__(serde=JsonPlusSerializer(pickle_fallback=False))
        self.store, self.customer, self.run_id, self.owner = store, customer, run_id, owner

    def config(self, checkpoint_id=None):
        values = {'thread_id': self.run_id, 'checkpoint_ns': ''}
        if checkpoint_id:
            values['checkpoint_id'] = checkpoint_id
        return {'configurable': values, 'recursion_limit': 32, 'callbacks': []}

    def check(self, config):
        c = config['configurable']
        if c['thread_id'] != self.run_id or c.get('checkpoint_ns', ''):
            raise ValueError('Invalid workflow scope.')

    def fence(self, db):
        row = db.execute('SELECT lease_owner,lease_until FROM graph_runs WHERE id=? AND customer_id=?',
                         (self.run_id, self.customer)).fetchone()
        require(row is not None and row['lease_owner'] == self.owner and row['lease_until'] > time.time(),
                409, 'workflow_lease_lost', 'Lượt xử lý đã hết quyền chạy. Hãy thử lại.')

    def pack(self, value):
        kind, data = self.serde.dumps_typed(value)
        return json.dumps([kind, base64.b64encode(data).decode('ascii')])

    def unpack(self, value):
        kind, data = json.loads(value)
        return self.serde.loads_typed((kind, base64.b64decode(data)))

    def get_tuple(self, config):
        self.check(config)
        cid = config['configurable'].get('checkpoint_id')
        with self.store.connection() as db:
            self.fence(db)
            if cid:
                row = db.execute('SELECT * FROM graph_checkpoints WHERE run_id=? AND checkpoint_id=?',
                                 (self.run_id, cid)).fetchone()
            else:
                row = db.execute('SELECT * FROM graph_checkpoints WHERE run_id=? ORDER BY checkpoint_id DESC LIMIT 1',
                                 (self.run_id,)).fetchone()
            if row is None:
                return None
            writes = db.execute('''SELECT task_id,channel,value FROM graph_writes
                WHERE run_id=? AND checkpoint_id=? ORDER BY task_id,idx''',
                (self.run_id, row['checkpoint_id'])).fetchall()
        return CheckpointTuple(self.config(row['checkpoint_id']), self.unpack(row['checkpoint']),
                               self.unpack(row['metadata']),
                               self.config(row['parent_id']) if row['parent_id'] else None,
                               [(r['task_id'], r['channel'], self.unpack(r['value'])) for r in writes])

    def put(self, config, checkpoint, metadata, new_versions):
        self.check(config)
        # Deliberately exclude runnable config metadata, which could carry app secrets.
        safe_metadata = {k: v for k, v in metadata.items() if k in ('source', 'step', 'parents')}
        with self.store.connection(write=True) as db:
            self.fence(db)
            db.execute('''INSERT INTO graph_checkpoints VALUES (?,?,?,?,?)
                ON CONFLICT(run_id,checkpoint_id) DO UPDATE SET checkpoint=excluded.checkpoint,metadata=excluded.metadata''',
                (self.run_id, checkpoint['id'], config['configurable'].get('checkpoint_id'),
                 self.pack(checkpoint), self.pack(safe_metadata)))
        return self.config(checkpoint['id'])

    def put_writes(self, config, writes, task_id, task_path=''):
        self.check(config)
        with self.store.connection(write=True) as db:
            self.fence(db)
            for index, (channel, value) in enumerate(writes):
                index = WRITES_IDX_MAP.get(channel, index)
                suffix = 'DO UPDATE SET value=excluded.value,channel=excluded.channel' if index < 0 else 'DO NOTHING'
                db.execute('''INSERT INTO graph_writes VALUES (?,?,?,?,?,?)
                    ON CONFLICT(run_id,checkpoint_id,task_id,idx) ''' + suffix,
                    (self.run_id, config['configurable']['checkpoint_id'], task_id, index, channel, self.pack(value)))


@contextmanager
def workflow(store, customer, purpose, key, fingerprint, seed, *, expires_at=None):
    """One fenced owner per run, including across web processes; leases expire after crashes."""
    run_id = hashlib.sha256(json.dumps([customer, purpose, key]).encode()).hexdigest()
    owner, now = uuid.uuid4().hex, time.time()
    with store.connection(write=True) as db:
        db.execute('DELETE FROM graph_runs WHERE expires_at<? AND lease_until<?', (now, now))
        row = db.execute('SELECT * FROM graph_runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            db.execute('INSERT INTO graph_runs VALUES (?,?,?,?,?,?,?)',
                       (run_id, customer, fingerprint, json.dumps(seed), expires_at or now+1800, owner, now+180))
        else:
            require(row['customer_id'] == customer and row['fingerprint'] == fingerprint, 409,
                    'request_conflict', 'Mã yêu cầu đã dùng cho nội dung, quyền hoặc nguồn model khác.')
            require(row['lease_until'] <= now, 429, 'workflow_busy', 'Yêu cầu này đang được xử lý. Hãy thử lại sau.')
            seed = json.loads(row['seed'])
            db.execute('UPDATE graph_runs SET lease_owner=?,lease_until=? WHERE id=?', (owner, now+180, run_id))
    saver = SqlSaver(store, customer, run_id, owner)
    try:
        yield saver, seed
    finally:
        with store.connection(write=True) as db:
            db.execute('UPDATE graph_runs SET lease_owner=NULL,lease_until=0 WHERE id=? AND lease_owner=?', (run_id, owner))
