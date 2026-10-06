"""Unit tests for Multi-Tenant ToolCache and Invalidation Race Discard (F13 / AC-12)."""
import threading
import time
import unittest

from retailops.business.cache import ToolCache


class ToolCacheConcurrencyTests(unittest.TestCase):
    def test_tool_cache_invalidation_race_discard(self):
        """Canonical test name matching AC-12 specification:
        In-flight tool write is discarded if cache_epoch was bumped by Manager invalidation.
        """
        cache = ToolCache(default_ttl=180.0)
        tenant_id = "T-001"
        customer = "C-001"
        tool_name = "get_order"
        arguments = {"order_id": "O-101"}

        # Initial state: epoch is 0
        read_epoch = cache.get_epoch(tenant_id, customer)
        self.assertEqual(read_epoch, 0)

        # Thread 1 starts tool execution with read_epoch = 0
        # While tool execution is "in-flight", Manager updates order and invalidates cache in Thread 2
        invalidation_barrier = threading.Barrier(2)
        write_result = [None]

        def manager_thread():
            invalidation_barrier.wait()
            # Manager commits DB update and invalidates cache, bumping epoch to 1
            removed = cache.invalidate(tenant_id, customer)
            self.assertEqual(cache.get_epoch(tenant_id, customer), 1)

        def tool_writer_thread():
            invalidation_barrier.wait()
            time.sleep(0.01)  # Ensure manager invalidation runs first
            # Attempt to write stale result using the pre-captured read_epoch (0)
            stale_order = {"order": {"id": "O-101", "status": "pending", "version": 1}}
            res = cache.set(
                tenant_id,
                customer,
                tool_name,
                arguments,
                stale_order,
                read_epoch=read_epoch,
            )
            write_result[0] = res

        t_mgr = threading.Thread(target=manager_thread)
        t_tool = threading.Thread(target=tool_writer_thread)
        t_mgr.start()
        t_tool.start()
        t_mgr.join(timeout=1.0)
        t_tool.join(timeout=1.0)

        # 1. Stale write MUST be rejected by CAS
        self.assertFalse(write_result[0])

        # 2. Cache MUST NOT contain the stale entry
        cached = cache.get(tenant_id, customer, tool_name, arguments)
        self.assertIsNone(cached)

    def test_multi_tenant_isolation_same_customer_id(self):
        """Cross-tenant collision prevention: two tenants with same customer_id are fully isolated."""
        cache = ToolCache(default_ttl=180.0)
        customer = "C-001"
        tool_name = "get_order"
        arguments = {"order_id": "O-101"}

        res_t1 = {"order": {"id": "O-101", "tenant": "T-001", "status": "pending"}}
        res_t2 = {"order": {"id": "O-101", "tenant": "T-002", "status": "delivered"}}

        # Set for T-001
        self.assertTrue(cache.set("T-001", customer, tool_name, arguments, res_t1))
        # Set for T-002
        self.assertTrue(cache.set("T-002", customer, tool_name, arguments, res_t2))

        # Check values are isolated
        self.assertEqual(cache.get("T-001", customer, tool_name, arguments)["order"]["tenant"], "T-001")
        self.assertEqual(cache.get("T-002", customer, tool_name, arguments)["order"]["tenant"], "T-002")

        # Invalidate T-001 only
        cache.invalidate("T-001", customer)

        # T-001 cache is gone
        self.assertIsNone(cache.get("T-001", customer, tool_name, arguments))
        # T-002 cache remains intact!
        self.assertIsNotNone(cache.get("T-002", customer, tool_name, arguments))
        self.assertEqual(cache.get("T-002", customer, tool_name, arguments)["order"]["tenant"], "T-002")

    def test_successful_cas_write_when_epoch_unchanged(self):
        """When epoch does not change during in-flight execution, CAS succeeds."""
        cache = ToolCache(default_ttl=180.0)
        epoch = cache.get_epoch("T-001", "C-001")
        success = cache.set(
            "T-001",
            "C-001",
            "get_order",
            {"order_id": "O-101"},
            {"order": {"id": "O-101", "status": "delivered"}},
            read_epoch=epoch,
        )
        self.assertTrue(success)
        cached = cache.get("T-001", "C-001", "get_order", {"order_id": "O-101"})
        self.assertIsNotNone(cached)
        self.assertEqual(cached["order"]["status"], "delivered")


if __name__ == "__main__":
    unittest.main()
