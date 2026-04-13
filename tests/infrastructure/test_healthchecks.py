"""Validate health check configurations for infrastructure services."""


def _get_healthcheck(compose_data, service_name) -> dict | None:
    return compose_data["services"][service_name].get("healthcheck")


def test_postgres_has_healthcheck(compose_data):
    hc = _get_healthcheck(compose_data, "litellm-db")
    assert hc is not None, "litellm-db should define a healthcheck"


def test_postgres_healthcheck_command(compose_data):
    hc = _get_healthcheck(compose_data, "litellm-db")
    test_cmd = hc["test"]
    # test can be a list like ["CMD-SHELL", "pg_isready -U litellm"]
    joined = " ".join(test_cmd) if isinstance(test_cmd, list) else test_cmd
    assert "pg_isready" in joined
    assert "-U litellm" in joined


def test_litellm_has_healthcheck(compose_data):
    hc = _get_healthcheck(compose_data, "litellm")
    assert hc is not None, "litellm should define a healthcheck"


def test_litellm_healthcheck_url(compose_data):
    hc = _get_healthcheck(compose_data, "litellm")
    test_cmd = hc["test"]
    joined = " ".join(test_cmd) if isinstance(test_cmd, list) else test_cmd
    assert "health/liveliness" in joined
    assert "localhost:4000" in joined


def test_litellm_healthcheck_has_start_period(compose_data):
    hc = _get_healthcheck(compose_data, "litellm")
    assert "start_period" in hc, "litellm healthcheck should have start_period (slow startup)"


def test_redis_has_no_healthcheck(compose_data):
    """Document current state: Redis has no healthcheck defined."""
    hc = _get_healthcheck(compose_data, "redis")
    assert hc is None, "Redis currently has no healthcheck (update this test if one is added)"


def test_frontend_has_no_healthcheck(compose_data):
    """Document current state: Frontend has no healthcheck defined."""
    hc = _get_healthcheck(compose_data, "chainlit-frontend")
    assert hc is None, "Frontend currently has no healthcheck (update this test if one is added)"
