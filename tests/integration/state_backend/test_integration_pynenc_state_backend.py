from typing import TYPE_CHECKING

from pynenc.call import Call
from pynenc.invocation import DistributedInvocation
from pynenc_tests.integration.state_backend.all_tests import *
from pynenc_tests.integration.state_backend.test_state_backend import dummy

if TYPE_CHECKING:
    from pynenc.app import Pynenc


def test_store_invocation_with_parent_event_round_trips_and_indexes(
    app_instance: "Pynenc",
) -> None:
    dummy.app = app_instance

    invocation = DistributedInvocation.from_parent(
        Call(dummy),
        parent_event_id="evt-redis-int-1",
    )

    stored = app_instance.state_backend.get_invocation(invocation.invocation_id)

    assert stored.workflow is None
    assert stored.parent_event_id == "evt-redis-int-1"
    assert list(
        app_instance.state_backend.get_invocations_by_parent_event("evt-redis-int-1")
    ) == [invocation.invocation_id]
