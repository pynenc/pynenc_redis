from typing import TYPE_CHECKING

import pytest
from docker.errors import DockerException
from pynenc import PynencBuilder
from testcontainers.redis import RedisContainer

if TYPE_CHECKING:
    from collections.abc import Generator

    from pynenc import Pynenc


@pytest.fixture(scope="function")
def app_instance_builder() -> "Generator['PynencBuilder', None, None]":
    """
    Fixture that provides a Pynenc app instance with a real Redis backend,
    using testcontainers to start a Redis container for integration tests.

    :return: Generator yielding a Pynenc app instance with Redis backend
    :raises RuntimeError: If Docker is not running or accessible
    """
    try:
        with RedisContainer("redis:7.2.3") as redis_container:
            redis_url = f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}/0"
            yield PynencBuilder().redis(url=redis_url)
    except DockerException as e:
        raise RuntimeError(
            "Docker is not running or not accessible. Please start Docker to run integration tests."
        ) from e


@pytest.fixture(scope="function")
def app_instance(
    app_instance_builder: "PynencBuilder",
) -> "Generator['Pynenc', None, None]":
    """
    Fixture that provides a Pynenc app instance built from the app_instance_builder.

    :param app_instance_builder: Fixture providing a PynencBuilder instance
    :return: Generator yielding a built Pynenc app instance
    """
    app = app_instance_builder.build()
    yield app
