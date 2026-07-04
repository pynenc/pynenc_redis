from typing import TYPE_CHECKING

import pytest
from pynenc_tests.unit.trigger.all_tests import *
from pynenc_tests.unit.trigger.test_trigger_all_instances import add
from pynenc_tests.unit.trigger.test_trigger_backend_monitoring import (
    trigger_target_task,
)

if TYPE_CHECKING:
    from pynenc.app import Pynenc
    from pynenc.trigger import BaseTrigger


@pytest.fixture
def trigger(app_instance: "Pynenc") -> "BaseTrigger":
    """Bind shared module-level tasks to the plugin app under test."""
    add.app = app_instance
    trigger_target_task.app = app_instance
    return app_instance.trigger
