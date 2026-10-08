"""Dataclasses for Docker Engine API payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from anchorage.docker._time import from_unix, parse_rfc3339
from anchorage.docker.errors import ServerError

COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"


def _labels(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(k): str(v) for k, v in value.items()}


def _str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v) for v in value)


def _short(container_id: str) -> str:
    return container_id.removeprefix("sha256:")[:12]


@dataclass(frozen=True, slots=True)
class PortBinding:
    private_port: int
    protocol: str
    public_port: int | None = None
    host_ip: str | None = None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> PortBinding:
        public = data.get("PublicPort")
        return cls(
            private_port=int(data["PrivatePort"]),
            protocol=str(data.get("Type") or "tcp"),
            public_port=int(public) if public else None,
            host_ip=str(data["IP"]) if data.get("IP") else None,
        )


def _normalize_ports(bindings: list[PortBinding]) -> tuple[PortBinding, ...]:
    """Drop duplicate IPv4/IPv6 entries for the same mapping and sort by private port."""
    unique: dict[tuple[int, str, int | None], PortBinding] = {}
    for binding in bindings:
        key = (binding.private_port, binding.protocol, binding.public_port)
        unique.setdefault(key, binding)

    def sort_key(b: PortBinding) -> tuple[int, str, int]:
        return (b.private_port, b.protocol, b.public_port or 0)

    return tuple(sorted(unique.values(), key=sort_key))


def parse_port_map(ports: Mapping[str, Any] | None) -> tuple[PortBinding, ...]:
    """Parse the ``NetworkSettings.Ports`` map of an inspect payload."""
    if not ports:
        return ()
    bindings: list[PortBinding] = []
    for spec, hosts in ports.items():
        port_text, _, protocol = spec.partition("/")
        private_port = int(port_text)
        protocol = protocol or "tcp"
        if not hosts:
            bindings.append(PortBinding(private_port=private_port, protocol=protocol))
            continue
        for host in hosts:
            host_port = host.get("HostPort")
            bindings.append(
                PortBinding(
                    private_port=private_port,
                    protocol=protocol,
                    public_port=int(host_port) if host_port else None,
                    host_ip=str(host["HostIp"]) if host.get("HostIp") else None,
                )
            )
    return _normalize_ports(bindings)


@dataclass(frozen=True, slots=True)
class Container:
    """One row of ``GET /containers/json``."""

    id: str
    name: str
    image: str
    image_id: str
    command: str
    state: str
    status: str
    created: datetime
    ports: tuple[PortBinding, ...] = ()
    labels: dict[str, str] = field(default_factory=dict)
    mounts: tuple[Mount, ...] = ()
    networks: dict[str, str] = field(default_factory=dict)

    @property
    def short_id(self) -> str:
        return _short(self.id)

    @property
    def compose_project(self) -> str | None:
        return self.labels.get(COMPOSE_PROJECT_LABEL)

    @property
    def compose_service(self) -> str | None:
        return self.labels.get(COMPOSE_SERVICE_LABEL)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Container:
        container_id = str(data["Id"])
        names = data.get("Names") or []
        name = str(names[0]).lstrip("/") if names else _short(container_id)
        raw_ports = data.get("Ports") or []
        settings = data.get("NetworkSettings") or {}
        attached = settings.get("Networks") or {}
        return cls(
            id=container_id,
            name=name,
            image=str(data.get("Image") or ""),
            image_id=str(data.get("ImageID") or ""),
            command=str(data.get("Command") or ""),
            state=str(data.get("State") or "unknown"),
            status=str(data.get("Status") or ""),
            created=from_unix(int(data.get("Created") or 0)),
            ports=_normalize_ports([PortBinding.from_api(p) for p in raw_ports]),
            labels=_labels(data.get("Labels")),
            mounts=tuple(Mount.from_api(m) for m in data.get("Mounts") or []),
            networks={str(n): str((v or {}).get("IPAddress") or "") for n, v in attached.items()},
        )


@dataclass(frozen=True, slots=True)
class ContainerState:
    status: str
    running: bool
    paused: bool
    restarting: bool
    exit_code: int
    started_at: datetime | None
    finished_at: datetime | None
    health: str | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> ContainerState:
        health = data.get("Health")
        health_status: str | None = None
        if isinstance(health, Mapping) and health.get("Status"):
            health_status = str(health["Status"])
        return cls(
            status=str(data.get("Status") or "unknown"),
            running=bool(data.get("Running", False)),
            paused=bool(data.get("Paused", False)),
            restarting=bool(data.get("Restarting", False)),
            exit_code=int(data.get("ExitCode") or 0),
            started_at=parse_rfc3339(data.get("StartedAt")),
            finished_at=parse_rfc3339(data.get("FinishedAt")),
            health=health_status,
        )


@dataclass(frozen=True, slots=True)
class Mount:
    type: str
    source: str
    destination: str
    mode: str
    read_write: bool
    name: str | None = None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Mount:
        return cls(
            type=str(data.get("Type") or ""),
            source=str(data.get("Source") or ""),
            destination=str(data.get("Destination") or ""),
            mode=str(data.get("Mode") or ""),
            read_write=bool(data.get("RW", True)),
            name=str(data["Name"]) if data.get("Name") else None,
        )


@dataclass(frozen=True, slots=True)
class NetworkAttachment:
    name: str
    ip_address: str
    gateway: str
    prefix_len: int
    mac_address: str

    @classmethod
    def from_api(cls, name: str, data: Mapping[str, Any]) -> NetworkAttachment:
        return cls(
            name=name,
            ip_address=str(data.get("IPAddress") or ""),
            gateway=str(data.get("Gateway") or ""),
            prefix_len=int(data.get("IPPrefixLen") or 0),
            mac_address=str(data.get("MacAddress") or ""),
        )


@dataclass(frozen=True, slots=True)
class ContainerDetails:
    """Result of ``GET /containers/{id}/json``."""

    id: str
    name: str
    image: str
    image_id: str
    created: datetime | None
    command: tuple[str, ...]
    state: ContainerState
    restart_policy: str
    tty: bool
    env: tuple[str, ...]
    labels: dict[str, str]
    mounts: tuple[Mount, ...]
    networks: tuple[NetworkAttachment, ...]
    ports: tuple[PortBinding, ...]

    @property
    def short_id(self) -> str:
        return _short(self.id)

    @property
    def compose_project(self) -> str | None:
        return self.labels.get(COMPOSE_PROJECT_LABEL)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> ContainerDetails:
        config = data.get("Config") or {}
        host_config = data.get("HostConfig") or {}
        restart = host_config.get("RestartPolicy") or {}
        settings = data.get("NetworkSettings") or {}
        networks = settings.get("Networks") or {}
        path = data.get("Path")
        command = ((str(path),) if path else ()) + _str_tuple(data.get("Args"))
        network_attachments = (
            NetworkAttachment.from_api(str(n), v or {}) for n, v in networks.items()
        )
        return cls(
            id=str(data["Id"]),
            name=str(data.get("Name") or "").lstrip("/") or _short(str(data["Id"])),
            image=str(config.get("Image") or ""),
            image_id=str(data.get("Image") or ""),
            created=parse_rfc3339(data.get("Created")),
            command=command,
            state=ContainerState.from_api(data.get("State") or {}),
            restart_policy=str(restart.get("Name") or "no"),
            tty=bool(config.get("Tty", False)),
            env=_str_tuple(config.get("Env")),
            labels=_labels(config.get("Labels")),
            mounts=tuple(Mount.from_api(m) for m in data.get("Mounts") or []),
            networks=tuple(network_attachments),
            ports=parse_port_map(settings.get("Ports")),
        )


def split_reference(reference: str) -> tuple[str, str]:
    """Split ``repo:tag`` into its parts; a missing tag means ``latest``."""
    slash = reference.rfind("/")
    colon = reference.rfind(":")
    if colon > slash:
        return reference[:colon], reference[colon + 1 :]
    return reference, "latest"


@dataclass(frozen=True, slots=True)
class Image:
    """One row of ``GET /images/json``."""

    id: str
    repo_tags: tuple[str, ...]
    repo_digests: tuple[str, ...]
    created: datetime
    size: int
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def short_id(self) -> str:
        return _short(self.id)

    @property
    def dangling(self) -> bool:
        return all(tag.startswith("<none>") for tag in self.repo_tags)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Image:
        return cls(
            id=str(data["Id"]),
            repo_tags=_str_tuple(data.get("RepoTags")),
            repo_digests=_str_tuple(data.get("RepoDigests")),
            created=from_unix(int(data.get("Created") or 0)),
            size=int(data.get("Size") or 0),
            labels=_labels(data.get("Labels")),
        )


@dataclass(frozen=True, slots=True)
class ImageDetails:
    """Result of ``GET /images/{name}/json``."""

    id: str
    repo_tags: tuple[str, ...]
    created: datetime | None
    size: int
    architecture: str
    os: str
    author: str
    env: tuple[str, ...]
    cmd: tuple[str, ...]
    entrypoint: tuple[str, ...]
    exposed_ports: tuple[str, ...]
    working_dir: str
    labels: dict[str, str]

    @property
    def short_id(self) -> str:
        return _short(self.id)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> ImageDetails:
        config = data.get("Config") or {}
        exposed = config.get("ExposedPorts") or {}
        return cls(
            id=str(data["Id"]),
            repo_tags=_str_tuple(data.get("RepoTags")),
            created=parse_rfc3339(data.get("Created")),
            size=int(data.get("Size") or 0),
            architecture=str(data.get("Architecture") or ""),
            os=str(data.get("Os") or ""),
            author=str(data.get("Author") or ""),
            env=_str_tuple(config.get("Env")),
            cmd=_str_tuple(config.get("Cmd")),
            entrypoint=_str_tuple(config.get("Entrypoint")),
            exposed_ports=tuple(sorted(str(p) for p in exposed)),
            working_dir=str(config.get("WorkingDir") or ""),
            labels=_labels(config.get("Labels")),
        )


@dataclass(frozen=True, slots=True)
class ImageLayer:
    """One row of ``GET /images/{name}/history``."""

    id: str
    created: datetime
    created_by: str
    size: int
    comment: str
    tags: tuple[str, ...]

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> ImageLayer:
        return cls(
            id=str(data.get("Id") or ""),
            created=from_unix(int(data.get("Created") or 0)),
            created_by=str(data.get("CreatedBy") or ""),
            size=int(data.get("Size") or 0),
            comment=str(data.get("Comment") or ""),
            tags=_str_tuple(data.get("Tags")),
        )


@dataclass(frozen=True, slots=True)
class VersionInfo:
    version: str
    api_version: str
    min_api_version: str
    os: str
    arch: str
    kernel_version: str

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> VersionInfo:
        return cls(
            version=str(data.get("Version") or ""),
            api_version=str(data.get("ApiVersion") or ""),
            min_api_version=str(data.get("MinAPIVersion") or ""),
            os=str(data.get("Os") or ""),
            arch=str(data.get("Arch") or ""),
            kernel_version=str(data.get("KernelVersion") or ""),
        )


@dataclass(frozen=True, slots=True)
class PruneResult:
    deleted: tuple[str, ...]
    untagged: tuple[str, ...]
    space_reclaimed: int

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> PruneResult:
        entries = data.get("ImagesDeleted") or []
        deleted = [str(e["Deleted"]) for e in entries if e.get("Deleted")]
        for key in ("VolumesDeleted", "NetworksDeleted", "ContainersDeleted"):
            deleted.extend(str(item) for item in data.get(key) or [])
        return cls(
            deleted=tuple(deleted),
            untagged=tuple(str(e["Untagged"]) for e in entries if e.get("Untagged")),
            space_reclaimed=int(data.get("SpaceReclaimed") or 0),
        )


@dataclass(frozen=True, slots=True)
class Volume:
    """One entry of ``GET /volumes``."""

    name: str
    driver: str
    mountpoint: str
    created: datetime | None
    scope: str
    labels: dict[str, str] = field(default_factory=dict)
    options: dict[str, str] = field(default_factory=dict)

    @property
    def compose_project(self) -> str | None:
        return self.labels.get(COMPOSE_PROJECT_LABEL)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Volume:
        return cls(
            name=str(data["Name"]),
            driver=str(data.get("Driver") or ""),
            mountpoint=str(data.get("Mountpoint") or ""),
            created=parse_rfc3339(data.get("CreatedAt")),
            scope=str(data.get("Scope") or "local"),
            labels=_labels(data.get("Labels")),
            options=_labels(data.get("Options")),
        )


@dataclass(frozen=True, slots=True)
class Subnet:
    subnet: str
    gateway: str


@dataclass(frozen=True, slots=True)
class Network:
    """One entry of ``GET /networks``."""

    id: str
    name: str
    driver: str
    scope: str
    created: datetime | None
    internal: bool
    attachable: bool
    ingress: bool
    ipv6: bool
    subnets: tuple[Subnet, ...] = ()
    labels: dict[str, str] = field(default_factory=dict)
    options: dict[str, str] = field(default_factory=dict)

    @property
    def short_id(self) -> str:
        return _short(self.id)

    @property
    def compose_project(self) -> str | None:
        return self.labels.get(COMPOSE_PROJECT_LABEL)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Network:
        ipam = data.get("IPAM") or {}
        config = ipam.get("Config") or []
        return cls(
            id=str(data.get("Id") or ""),
            name=str(data["Name"]),
            driver=str(data.get("Driver") or ""),
            scope=str(data.get("Scope") or "local"),
            created=parse_rfc3339(data.get("Created")),
            internal=bool(data.get("Internal", False)),
            attachable=bool(data.get("Attachable", False)),
            ingress=bool(data.get("Ingress", False)),
            ipv6=bool(data.get("EnableIPv6", False)),
            subnets=tuple(
                Subnet(str(c.get("Subnet") or ""), str(c.get("Gateway") or "")) for c in config
            ),
            labels=_labels(data.get("Labels")),
            options=_labels(data.get("Options")),
        )


@dataclass(frozen=True, slots=True)
class Event:
    """One entry of the ``GET /events`` stream."""

    type: str
    action: str
    actor_id: str
    attributes: dict[str, str]
    time: datetime

    @property
    def name(self) -> str | None:
        return self.attributes.get("name")

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Event:
        actor = data.get("Actor") or {}
        nanos = data.get("timeNano")
        if nanos:
            total = int(nanos)
            time = from_unix(total // 1_000_000_000) + timedelta(
                microseconds=(total % 1_000_000_000) // 1000
            )
        else:
            time = from_unix(int(data.get("time") or 0))
        return cls(
            type=str(data.get("Type") or ""),
            action=str(data.get("Action") or ""),
            actor_id=str(actor.get("ID") or ""),
            attributes=_labels(actor.get("Attributes")),
            time=time,
        )


def _cpu_percent(cpu: Mapping[str, Any], precpu: Mapping[str, Any]) -> float:
    usage = cpu.get("cpu_usage") or {}
    prev_usage = precpu.get("cpu_usage") or {}
    prev_system = int(precpu.get("system_cpu_usage") or 0)
    if prev_system == 0:
        return 0.0
    cpu_delta = int(usage.get("total_usage") or 0) - int(prev_usage.get("total_usage") or 0)
    system_delta = int(cpu.get("system_cpu_usage") or 0) - prev_system
    if cpu_delta <= 0 or system_delta <= 0:
        return 0.0
    online = int(cpu.get("online_cpus") or 0) or len(usage.get("percpu_usage") or []) or 1
    return cpu_delta / system_delta * online * 100.0


def _memory_usage(memory: Mapping[str, Any]) -> int:
    usage = int(memory.get("usage") or 0)
    stats = memory.get("stats") or {}
    if "inactive_file" in stats:
        return max(usage - int(stats["inactive_file"] or 0), 0)
    if "cache" in stats:
        return max(usage - int(stats["cache"] or 0), 0)
    return usage


def _blkio(entries: Any, op: str) -> int:
    if not isinstance(entries, list):
        return 0
    return sum(int(e.get("value") or 0) for e in entries if str(e.get("op") or "").lower() == op)


@dataclass(frozen=True, slots=True)
class ContainerStats:
    """One sample of ``GET /containers/{id}/stats``. Byte counters are cumulative."""

    read_at: datetime | None
    cpu_percent: float
    memory_usage: int
    memory_limit: int
    network_rx: int
    network_tx: int
    block_read: int
    block_write: int
    pids: int

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> ContainerStats:
        memory = data.get("memory_stats") or {}
        networks = data.get("networks") or {}
        blkio = (data.get("blkio_stats") or {}).get("io_service_bytes_recursive")
        return cls(
            read_at=parse_rfc3339(data.get("read")),
            cpu_percent=_cpu_percent(data.get("cpu_stats") or {}, data.get("precpu_stats") or {}),
            memory_usage=_memory_usage(memory),
            memory_limit=int(memory.get("limit") or 0),
            network_rx=sum(int(n.get("rx_bytes") or 0) for n in networks.values()),
            network_tx=sum(int(n.get("tx_bytes") or 0) for n in networks.values()),
            block_read=_blkio(blkio, "read"),
            block_write=_blkio(blkio, "write"),
            pids=int((data.get("pids_stats") or {}).get("current") or 0),
        )


@dataclass(frozen=True, slots=True)
class LogLine:
    stream: str
    text: str
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class PullProgress:
    """One JSON line of ``POST /images/create``."""

    status: str
    layer_id: str | None = None
    current: int | None = None
    total: int | None = None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> PullProgress:
        if data.get("error"):
            detail = data.get("errorDetail") or {}
            raise ServerError(str(detail.get("message") or data["error"]))
        detail = data.get("progressDetail") or {}
        current = detail.get("current")
        total = detail.get("total")
        return cls(
            status=str(data.get("status") or ""),
            layer_id=str(data["id"]) if data.get("id") else None,
            current=int(current) if current is not None else None,
            total=int(total) if total is not None else None,
        )
