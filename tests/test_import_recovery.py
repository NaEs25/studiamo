import pytest
from app.import_manager import ImportQueueManager


def test_inflight_tracking():
    mgr = ImportQueueManager.get_instance()
    assert not mgr.is_task_inflight(999999)
    mgr._inflight_task_ids.add(999999)
    try:
        assert mgr.is_task_inflight(999999)
    finally:
        mgr._inflight_task_ids.discard(999999)
    assert not mgr.is_task_inflight(999999)


def test_reset_inflight_empty():
    mgr = ImportQueueManager.get_instance()
    # Should safely no-op without error when empty
    mgr.reset_inflight_tasks_on_shutdown()
