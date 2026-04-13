"""Validate network configuration."""


def test_agent_network_defined(compose_data):
    networks = compose_data.get("networks", {})
    assert "agent-network" in networks


def test_agent_network_is_bridge(compose_data):
    network = compose_data["networks"]["agent-network"]
    assert network.get("driver") == "bridge"


def test_all_services_on_agent_network(compose_data, infrastructure_services):
    for svc_name in infrastructure_services:
        svc = compose_data["services"][svc_name]
        networks = svc.get("networks", [])
        if isinstance(networks, list):
            assert "agent-network" in networks, (
                f"Service '{svc_name}' not on agent-network"
            )
        elif isinstance(networks, dict):
            assert "agent-network" in networks, (
                f"Service '{svc_name}' not on agent-network"
            )


def test_no_service_on_host_network(compose_data, infrastructure_services):
    for svc_name in infrastructure_services:
        svc = compose_data["services"][svc_name]
        assert svc.get("network_mode") != "host", (
            f"Service '{svc_name}' should not use host network mode"
        )
