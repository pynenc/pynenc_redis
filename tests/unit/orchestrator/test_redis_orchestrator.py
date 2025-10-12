from typing import TYPE_CHECKING

import pytest
from pynenc_tests.conftest import MockPynenc

from pynenc_redis.orchestrator.redis_orchestrator import PendingInvocationLockError

if TYPE_CHECKING:
    from pynenc.app import Pynenc
    from pynenc.invocation import DistributedInvocation

    from pynenc_redis.orchestrator.redis_orchestrator import RedisOrchestrator


_mock_base_app = MockPynenc()


@_mock_base_app.task
def task0() -> None: ...


def test_set_pending_status_lock_error(app_instance: "Pynenc") -> None:
    """
    Test that _set_invocation_pending_status raises PendingInvocationLockError
    when the lock cannot be acquired due to contention.
    """
    # Create a test invocation
    task0.app = app_instance
    invocation: "DistributedInvocation" = task0()  # type: ignore
    orchestrator: "RedisOrchestrator" = app_instance.orchestrator  # type: ignore

    # Register the invocation
    orchestrator._register_new_invocations([invocation])

    # reduce lock time
    app_instance.conf.max_pending_seconds = 0.1

    # Manually acquire the lock to simulate contention
    lock_key = f"lock:pending_status:{invocation.invocation_id}"
    lock = orchestrator.client.lock(lock_key, blocking_timeout=0)
    lock.acquire()

    # Attempt to set pending status should fail with lock error
    with pytest.raises(PendingInvocationLockError):
        orchestrator._set_invocation_pending_status(invocation.invocation_id)
