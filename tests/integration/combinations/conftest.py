from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from _pytest.monkeypatch import MonkeyPatch
from pynenc.serializer import BaseSerializer
from pynenc.util.subclasses import get_all_subclasses
from pynenc_tests.util import get_module_name
from pynenc_tests.util.subclasses import get_runner_subclasses

if TYPE_CHECKING:
    from _pytest.fixtures import FixtureRequest
    from pynenc import PynencBuilder
    from pynenc.app import Pynenc


@dataclass(frozen=True)
class AppComponents:
    """Component combination for testing."""

    serializer: type
    runner: type

    @property
    def combination_id(self) -> str:
        """
        Compute a stable identifier for the component combination.

        :return: String identifier for the combination
        """
        return f"{self.runner.__name__}({self.serializer.__name__})"


def build_test_combinations() -> list[AppComponents]:
    """
    Build component combinations for testing, pairing runners (longer) with serializers (shorter).

    Always treats runners as the longer list and serializers as the shorter list.
    If this is not the case, an assertion will fail, prompting manual correction.

    This ensures deterministic test IDs and reliable test discovery.

    :return: List of component combinations, one per runner
    """

    # Sort to ensure same fixture params and ids across runs
    runners = sorted(get_runner_subclasses(), key=lambda cls: cls.__name__)
    serializers = sorted(
        get_all_subclasses(BaseSerializer), key=lambda cls: cls.__name__
    )

    assert len(runners) >= len(serializers), (
        "Expected runners to be the longer list. "
        "If not, flip the logic in build_test_combinations."
        "So we test all the existing subclasses of both."
    )

    combinations: list[AppComponents] = []
    for i, runner_cls in enumerate(runners):
        serializer_cls = serializers[i % len(serializers)]
        combinations.append(AppComponents(serializer_cls, runner_cls))

    return combinations


@pytest.fixture(
    params=build_test_combinations(),
    ids=lambda comp: comp.combination_id,
)
def app_combination_instance(
    request: "FixtureRequest",
    app_instance_builder: "PynencBuilder",
    monkeypatch: MonkeyPatch,
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
    monkeypatch.setenv("PYNENC__SERIALIZER_CLS", components.serializer.__name__)
    monkeypatch.setenv("PYNENC__RUNNER_CLS", components.runner.__name__)
    monkeypatch.setenv("PYNENC__ORCHESTRATOR__CYCLE_CONTROL", "True")
    monkeypatch.setenv("PYNENC__REDIS_URL", app_instance_builder._config["redis_url"])
    monkeypatch.setenv("PYNENC__PRINT_ARGUMENTS", "False")

    app_instance = app_instance_builder.build()

    # Set additional environment variables for subprocess components
    monkeypatch.setenv(
        "PYNENC__ARG_CACHE_CLS", app_instance.arg_cache.__class__.__name__
    )
    monkeypatch.setenv(
        "PYNENC__ORCHESTRATOR_CLS", app_instance.orchestrator.__class__.__name__
    )
    monkeypatch.setenv("PYNENC__BROKER_CLS", app_instance.broker.__class__.__name__)
    monkeypatch.setenv(
        "PYNENC__STATE_BACKEND_CLS", app_instance.state_backend.__class__.__name__
    )
    monkeypatch.setenv(
        "PYNENC__LOGGING_LEVEL", app_instance_builder._config["logging_level"]
    )

    return app_instance
