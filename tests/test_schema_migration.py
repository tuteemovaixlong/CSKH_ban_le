"""Migrate actual unversioned business records without resetting orders or replay."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from retailops.business.store import BusinessStore
from retailops.identity.store import IdentityStore


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'business.sqlite3'

    def test_unversioned_schema_preserves_orders_audit_conversation_and_confirm_replay(self):
        # Layout used before the versioned schema, including conversations without provider_id.
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                CREATE TABLE orders(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL,name TEXT NOT NULL,
                    variant TEXT NOT NULL,amount INTEGER NOT NULL,status TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,cancel_reason TEXT);
                CREATE TABLE proposals(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL,
                    order_id TEXT NOT NULL REFERENCES orders(id),order_version INTEGER NOT NULL,
                    reason TEXT NOT NULL,expires_at REAL NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
                    confirm_key TEXT,result TEXT,UNIQUE(customer_id,confirm_key));
                CREATE TABLE business_events(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_id TEXT NOT NULL,
                    created_at REAL NOT NULL,kind TEXT NOT NULL,order_id TEXT,payload TEXT NOT NULL);
                CREATE TABLE conversations(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL,order_id TEXT,
                    product_id TEXT,revision INTEGER NOT NULL DEFAULT 0,expires_at REAL NOT NULL);
            ''')
            db.execute("INSERT INTO orders VALUES ('O-901','C-901','Old order','M',100,'cancelled',2,'ordered_by_mistake')")
            saved = {'order': {'id': 'O-901', 'status': 'cancelled', 'version': 2}, 'message': 'Saved result'}
            db.execute("INSERT INTO proposals VALUES ('old-proposal','C-901','O-901',1,'ordered_by_mistake',1,'confirmed',?,?)",
                       ('legacy-confirm-key', json.dumps(saved)))
            db.execute("INSERT INTO business_events VALUES (1,'C-901',1,'order_cancelled','O-901','{}')")
            db.execute("INSERT INTO conversations VALUES ('old-conversation','C-901','O-901',NULL,3,1)")
        for _ in range(2):  # Reopening must not rerun migrations or seed records.
            store = BusinessStore(self.path)
            self.assertEqual(store.orders('C-901')[0]['version'], 2)
            self.assertEqual(store.customer('C-901')['id'], 'C-901')
            self.assertEqual(len(store.events('C-901')), 1)
            self.assertTrue(store.confirm('C-901', 'old-proposal', {'confirmed': True}, 'legacy-confirm-key')['replayed'])
            with store.connection() as db:
                self.assertEqual(tuple(db.execute('SELECT * FROM retailops_schema').fetchone()), ('business', 2))
                row = db.execute('SELECT revision,provider_id FROM conversations').fetchone()
                self.assertEqual(tuple(row), (3, 'custom'))
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_v1_business_upgrades_once_preserving_existing_orders(self):
        store = BusinessStore(self.path)
        store.seed()
        with store.connection(write=True) as db:
            for name in ('graph_writes', 'graph_checkpoints', 'graph_runs'):
                db.execute('DROP TABLE '+name)
            db.execute("UPDATE retailops_schema SET version=1 WHERE component='business'")
        for _ in range(2):
            reopened = BusinessStore(self.path)
            self.assertEqual(reopened.orders('C-001')[0]['status'], 'pending')
            with reopened.connection() as db:
                self.assertEqual(db.execute('SELECT version FROM retailops_schema').fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT count(*) FROM graph_runs').fetchone()[0], 0)

    def test_failed_migration_rolls_back_ddl_and_version_marker(self):
        def fail(db):
            db.execute('CREATE TABLE partial_write(id TEXT)')
            raise ValueError('Fixture migration failure')
        with patch('retailops.business.store.initialize_schema', side_effect=fail), self.assertRaises(ValueError):
            BusinessStore(self.path)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])
        store = BusinessStore(self.path)
        self.assertEqual(store.orders('C-001'), [])

    def test_unknown_future_schema_and_wrong_component_are_rejected_without_downgrade(self):
        store = BusinessStore(self.path)
        store.seed()
        with store.connection(write=True) as db:
            db.execute('UPDATE retailops_schema SET version=99')
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            BusinessStore(self.path)
        with store.connection() as db:
            self.assertEqual(db.execute('SELECT version FROM retailops_schema').fetchone()[0], 99)
        identity_path = self.path.with_name('identity.sqlite3')
        IdentityStore(identity_path)
        with self.assertRaisesRegex(ValueError, 'another'):
            BusinessStore(identity_path)
        with self.assertRaisesRegex(ValueError, 'another'):
            IdentityStore(self.path)

    def test_customer_constraints_prevent_dangling_order_ownership(self):
        store = BusinessStore(self.path)
        store.seed()
        for sql in (
            "INSERT INTO orders(id,customer_id,name,variant,amount,status) VALUES('O-999','MISSING','x','x',1,'pending')",
            "UPDATE orders SET customer_id='MISSING' WHERE id='O-101'",
            "DELETE FROM customers WHERE id='C-001'",
            "UPDATE customers SET id='MISSING' WHERE id='C-001'",
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError), store.connection(write=True) as db:
                db.execute(sql)
        self.assertEqual(store.orders('C-001')[0]['id'], 'O-101')

    def test_live_repository_does_not_recreate_a_deleted_database(self):
        store = BusinessStore(self.path)
        self.path.unlink()
        with self.assertRaises(sqlite3.OperationalError):
            store.orders('C-001')
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
