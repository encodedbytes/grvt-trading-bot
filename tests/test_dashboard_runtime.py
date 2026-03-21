from __future__ import annotations

import json

from gravity_dca import dashboard_runtime


def test_docker_bin_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv("GRAVITY_DASHBOARD_DOCKER_BIN", "/custom/docker")
    assert dashboard_runtime.docker_bin() == "/custom/docker"


def test_docker_bin_raises_actionable_error_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("GRAVITY_DASHBOARD_DOCKER_BIN", raising=False)
    monkeypatch.setattr(dashboard_runtime.shutil, "which", lambda name: None)

    try:
        dashboard_runtime.docker_bin()
    except FileNotFoundError as exc:
        assert "docker CLI not found on PATH" in str(exc)
    else:
        raise AssertionError("docker_bin() should have raised FileNotFoundError")


def test_docker_socket_uses_docker_host(monkeypatch) -> None:
    monkeypatch.delenv("GRAVITY_DASHBOARD_DOCKER_SOCKET", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/test-docker.sock")
    assert dashboard_runtime.docker_socket_path() == "/var/run/test-docker.sock"


def test_fetch_bot_status_from_api_returns_first_successful_payload(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    class FakeResponse:
        status = 200

        def read(self) -> bytes:
            return json.dumps({"symbol": "ETH_USDT_Perp"}).encode("utf-8")

    class FakeConnection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            calls.append((host, port))
            self.host = host

        def request(self, method: str, path: str) -> None:
            if self.host == "172.18.0.2":
                raise OSError("unreachable")

        def getresponse(self) -> FakeResponse:
            return FakeResponse()

        def close(self) -> None:
            return None

    monkeypatch.setattr(dashboard_runtime.http.client, "HTTPConnection", FakeConnection)

    payload = dashboard_runtime.fetch_bot_status_from_api(
        dashboard_runtime.DockerContainer(
            id="abc123",
            name="grvt-momentum-eth",
            image="gravity-dca-bot:local",
            status="Up 1 minute",
            config_source=None,
            state_source=None,
            network_ips=["172.18.0.2", "172.18.0.3"],
        ),
        port=8788,
    )

    assert payload == {"symbol": "ETH_USDT_Perp"}
    assert calls == [("172.18.0.2", 8788), ("172.18.0.3", 8788)]


def test_list_running_bot_containers_includes_grid_named_container(monkeypatch) -> None:
    rows = [
        {
            "Id": "abc123def4567890",
            "Image": "custom:local",
            "Names": ["/grvt-grid-eth"],
            "Status": "Up 1 minute",
        },
        {
            "Id": "zzz999yyy8887777",
            "Image": "postgres:16",
            "Names": ["/postgres"],
            "Status": "Up 2 minutes",
        },
    ]
    inspect_payload = {
        "Mounts": [
            {"Destination": "/app/config.toml", "Source": "/tmp/config.toml"},
            {"Destination": "/state", "Source": "/tmp/state"},
        ],
        "NetworkSettings": {"Networks": {"bridge": {"IPAddress": "172.18.0.9"}}},
    }

    def fake_docker_api_get(path: str) -> str:
        if path == "/containers/json":
            return json.dumps(rows)
        if path == "/containers/abc123def4567890/json":
            return json.dumps(inspect_payload)
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(dashboard_runtime, "docker_api_get", fake_docker_api_get)

    containers = dashboard_runtime.list_running_bot_containers()

    assert len(containers) == 1
    assert containers[0].name == "grvt-grid-eth"
    assert containers[0].network_ips == ["172.18.0.9"]
