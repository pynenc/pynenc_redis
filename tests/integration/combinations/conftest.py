from typing import TYPE_CHECKING

import pytest
from _pytest.monkeypatch import MonkeyPatch

from pynenc_tests.integration.combinations.conftest import AppComponents
from pynenc.util.subclasses import get_all_subclasses
from pynenc_tests.util.subclasses import get_runner_subclasses
from pynenc_tests.util import get_module_name
from pynenc.serializer import BaseSerializer

from pynenc_redis.arg_cache import RedisArgCache
from pynenc_redis.broker import RedisBroker
from pynenc_redis.orchestrator import RedisOrchestrator
from pynenc_redis.state_backend import RedisStateBackend

if TYPE_CHECKING:
    from pynenc.app import Pynenc
    from pynenc import PynencBuilder
    from _pytest.fixtures import FixtureRequest

def build_test_combinations() -> list[AppComponents]:
    """Build the default list of AppComponents combinations."""
    combinations: list[AppComponents] = []
    for runner_cls in get_runner_subclasses():
        for serializer_cls in get_all_subclasses(BaseSerializer):
            combinations.append(
                AppComponents(
                    RedisArgCache, RedisBroker, RedisOrchestrator, RedisStateBackend, serializer_cls, runner_cls
                )
            )
    return combinations


@pytest.fixture(
    params=build_test_combinations(),
    ids=lambda comp: comp.combination_id,
)
def app_combination_instance(
    request: "FixtureRequest", app_instance_builder: "PynencBuilder", monkeypatch: MonkeyPatch
) -> "Pynenc":
    components: AppComponents = request.param
    test_module, test_name = get_module_name(request)
    app_id = f"{test_module}.{test_name}"
    app_instance_builder = app_instance_builder.app_id(app_id).logging_level("debug")
    app_instance_builder._config["serializer_cls"] = components.serializer.__name__
    app_instance_builder._config["runner_cls"] = components.runner.__name__

    # The builder is the cleanest way of building an app
    # However, in this hacky way of changing the app components associated to a task in the fly
    # when we open a subprocess, the environment variables would be propagated
    # and the app in pynenc_tests/integration/combinations/tasks.py
    # would be build with the correct components
    monkeypatch.setenv("PYNENC__APP_ID", f"{test_module}.{test_name}")
    monkeypatch.setenv("PYNENC__ARG_CACHE_CLS", components.arg_cache.__name__)
    monkeypatch.setenv("PYNENC__ORCHESTRATOR_CLS", components.orchestrator.__name__)
    monkeypatch.setenv("PYNENC__BROKER_CLS", components.broker.__name__)
    monkeypatch.setenv("PYNENC__SERIALIZER_CLS", components.serializer.__name__)
    monkeypatch.setenv("PYNENC__STATE_BACKEND_CLS", components.state_backend.__name__)
    monkeypatch.setenv("PYNENC__RUNNER_CLS", components.runner.__name__)
    monkeypatch.setenv("PYNENC__LOGGING_LEVEL", app_instance_builder._config["logging_level"])
    monkeypatch.setenv("PYNENC__ORCHESTRATOR__CYCLE_CONTROL", "True")
    monkeypatch.setenv("PYNENC__REDIS_URL", app_instance_builder._config["redis_url"] )
    monkeypatch.setenv("PYNENC__PRINT_ARGUMENTS", "False")

    app_instance = app_instance_builder.build()
    return app_instance