from __future__ import annotations

from dataclasses import dataclass
import http.client
import io
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tarfile
from typing import Any
from urllib.parse import quote, urlencode


LOGGER = logging.getLogger("gravity_dca.dashboard")


@dataclass(frozen=True)
class DockerContainer:
    id: str
    name: str
    image: str
    status: str
    config_source: Path | None
    state_source: Path | None
    network_ips: list[str]


def docker_bin() -> str:
    configured = os.environ.get("GRAVITY_DASHBOARD_DOCKER_BIN", "").strip()
    if configured:
        return configured
    discovered = shutil.which("docker")
    if discovered:
        return discovered
    raise FileNotFoundError(
        "docker CLI not found on PATH; mount /var/run/docker.sock or install Docker for host-side dashboard use"
    )


def docker_socket_path() -> str | None:
    configured = os.environ.get("GRAVITY_DASHBOARD_DOCKER_SOCKET", "").strip()
    if configured:
        return configured
    docker_host = os.environ.get("DOCKER_HOST", "").strip()
    if docker_host.startswith("unix://"):
        return docker_host[len("unix://") :]
    default = Path("/var/run/docker.sock")
    if default.exists():
        return str(default)
    return None


class UnixSocketHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 20) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._socket_path)


def docker_api_get(path: str, *, query: dict[str, str] | None = None) -> bytes:
    socket_path = docker_socket_path()
    if not socket_path:
        raise FileNotFoundError("docker socket not available")
    target = path
    if query:
        target += "?" + urlencode(query)
    connection = UnixSocketHTTPConnection(socket_path)
    try:
        connection.request("GET", target)
        response = connection.getresponse()
        payload = response.read()
    finally:
        connection.close()
    if response.status >= 400:
        message = payload.decode("utf-8", errors="replace").strip()
        raise OSError(f"Docker API GET {target} failed: {response.status} {response.reason}: {message}")
    return payload


def docker_api_read_file(container_id: str, path: str) -> bytes:
    payload = docker_api_get(
        f"/containers/{quote(container_id, safe='')}/archive",
        query={"path": path},
    )
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        member = archive.next()
        if member is None:
            raise FileNotFoundError(f"No file returned for container path {path}")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise FileNotFoundError(f"Container path {path} is not a regular file")
        return extracted.read()


def fetch_bot_status_from_api(container: DockerContainer, *, port: int) -> dict[str, Any] | None:
    for ip_address in container.network_ips:
        connection = http.client.HTTPConnection(ip_address, port, timeout=1.5)
        try:
            connection.request("GET", "/status")
            response = connection.getresponse()
            payload = response.read()
        except OSError:
            continue
        finally:
            connection.close()
        if response.status != 200:
            continue
        return json.loads(payload.decode("utf-8"))
    return None


def run_docker(args: list[str]) -> str:
    binary = docker_bin()
    LOGGER.info("docker %s", " ".join(args))
    completed = subprocess.run(
        [binary, *args],
        check=True,
        capture_output=True,
        text=True,
    )
    LOGGER.info("docker %s -> ok", " ".join(args))
    return completed.stdout


def container_state(status: str) -> str:
    lowered = status.lower()
    if lowered.startswith("up "):
        return "running"
    if lowered.startswith("exited"):
        return "exited"
    return lowered or "unknown"


def load_recent_log_info(container_name: str) -> tuple[str | None, str | None]:
    lines = get_container_logs(container_name, tail=40)
    if not lines:
        return None, None
    last_line = lines[-1] if lines else None
    recent_error = next((line for line in reversed(lines) if "ERROR" in line), None)
    return recent_error, last_line


def get_container_logs(container_name: str, *, tail: int = 200) -> list[str]:
    LOGGER.info("Loading logs for container=%s tail=%s", container_name, tail)
    try:
        try:
            payload = docker_api_get(
                f"/containers/{quote(container_name, safe='')}/logs",
                query={"stdout": "1", "stderr": "1", "tail": str(tail)},
            )
            combined = payload.decode("utf-8", errors="replace").strip()
        except (FileNotFoundError, OSError):
            binary = docker_bin()
            completed = subprocess.run(
                [binary, "logs", "--tail", str(tail), container_name],
                check=False,
                capture_output=True,
                text=True,
            )
            combined = "\n".join(
                line for line in [completed.stdout.strip(), completed.stderr.strip()] if line
            )
    except OSError:
        LOGGER.exception("Failed to load logs for container=%s", container_name)
        return []
    if not combined:
        LOGGER.info("No logs available for container=%s", container_name)
        return []
    lines = [line for line in combined.splitlines() if line.strip()]
    LOGGER.info("Loaded %s log lines for container=%s", len(lines), container_name)
    return lines


def find_mount_source(mounts: list[dict[str, Any]], destination: str) -> Path | None:
    for mount in mounts:
        if mount.get("Destination") == destination and mount.get("Source"):
            return Path(str(mount["Source"]))
    return None


def list_running_bot_containers() -> list[DockerContainer]:
    try:
        rows = json.loads(docker_api_get("/containers/json"))
        containers: list[DockerContainer] = []
        for row in rows:
            image = str(row.get("Image", ""))
            names = row.get("Names") or []
            name = str(names[0]).lstrip("/") if names else str(row.get("Names", ""))
            if "gravity-dca-bot" not in image and not name.startswith("grvt-dca"):
                continue
            inspect = json.loads(docker_api_get(f"/containers/{quote(str(row['Id']), safe='')}/json"))
            network_ips = [
                str(network.get("IPAddress", ""))
                for network in (inspect.get("NetworkSettings", {}).get("Networks", {}) or {}).values()
                if network.get("IPAddress")
            ]
            containers.append(
                DockerContainer(
                    id=str(row["Id"])[:12],
                    name=name,
                    image=image,
                    status=str(row.get("Status", "")),
                    config_source=find_mount_source(inspect.get("Mounts", []), "/app/config.toml"),
                    state_source=find_mount_source(inspect.get("Mounts", []), "/state"),
                    network_ips=network_ips,
                )
            )
        LOGGER.info("Discovered %s bot containers via Docker API", len(containers))
        return containers
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        LOGGER.info("Docker API unavailable; falling back to docker CLI", exc_info=True)

    raw = run_docker(["ps", "--format", "{{json .}}"])
    containers: list[DockerContainer] = []
    ids: list[str] = []
    rows = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        image = str(row.get("Image", ""))
        name = str(row.get("Names", ""))
        if "gravity-dca-bot" not in image and not name.startswith("grvt-dca"):
            continue
        rows.append(row)
        ids.append(str(row["ID"]))
    if not ids:
        LOGGER.info("No running bot containers matched Docker output")
        return []
    inspect = json.loads(run_docker(["inspect", *ids]))
    mounts_by_id = {str(item["Id"])[:12]: item.get("Mounts", []) for item in inspect}
    for row in rows:
        container_id = str(row["ID"])
        mounts = mounts_by_id.get(container_id, [])
        containers.append(
            DockerContainer(
                id=container_id,
                name=str(row["Names"]),
                image=str(row["Image"]),
                status=str(row["Status"]),
                config_source=find_mount_source(mounts, "/app/config.toml"),
                state_source=find_mount_source(mounts, "/state"),
                network_ips=[],
            )
        )
    LOGGER.info("Discovered %s bot containers via docker CLI", len(containers))
    return containers
