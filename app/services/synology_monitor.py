"""Privacy-safe, in-memory Synology health polling via PySNMP's async API."""

import asyncio
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from app.api.schemas.system_health import SynologyDiskHealth, SynologySystemHealth
from app.core.config import Settings, get_settings
from app.core.logging import logger

SCALARS = {
    "system_temperature_c": "1.3.6.1.4.1.6574.1.2.0",
    "cpu_percent": "1.3.6.1.4.1.6574.1.7.1.0",
    "memory_percent": "1.3.6.1.4.1.6574.1.7.2.0",
    "thermal_status_code": "1.3.6.1.4.1.6574.1.8.0",
    "load_average_1m": "1.3.6.1.4.1.2021.10.1.5.1",
    "uptime_seconds": "1.3.6.1.2.1.25.1.1.0",
}
DISK_COLUMNS = {
    "id": "1.3.6.1.4.1.6574.2.1.1.2",
    "model": "1.3.6.1.4.1.6574.2.1.1.3",
    "status_code": "1.3.6.1.4.1.6574.2.1.1.5",
    "temperature_c": "1.3.6.1.4.1.6574.2.1.1.6",
}

# Give FastAPI's lifespan generator time to yield before doing any PySNMP
# setup.  In particular, address resolution performed by a transport target
# must never delay Uvicorn's "Application startup complete" transition.
STARTUP_POLL_DELAY_SECONDS = 0.25


def _int(value: Any) -> int | None:
    try:
        if value is None or "No Such" in str(value) or str(value).strip() == "":
            return None
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def normalize_scalars(values: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: _int(values.get(key)) for key in SCALARS}
    load = normalized.pop("load_average_1m")
    uptime = normalized.pop("uptime_seconds")
    thermal = normalized.get("thermal_status_code")
    normalized.update(
        load_average_1m=load / 100 if load is not None else None,
        uptime_seconds=uptime / 100 if uptime is not None else None,
        thermal_status={1: "normal", 2: "failed"}.get(thermal, "unknown"),
    )
    return normalized


def normalize_disk(index: int, values: dict[str, Any]) -> SynologyDiskHealth | None:
    disk_id = str(values.get("id") or "").strip()
    if not disk_id or "No Such" in disk_id:
        return None
    status_code = _int(values.get("status_code"))
    model = str(values.get("model") or "").strip() or None
    if model and "No Such" in model:
        model = None
    return SynologyDiskHealth(
        snmp_index=index, id=disk_id, model=model, status_code=status_code,
        status={1: "normal", 2: "initialized", 3: "not_initialized", 4: "system_partition_failed", 5: "crashed"}.get(status_code, "unknown"),
        temperature_c=_int(values.get("temperature_c")),
    )


async def pysnmp_get(settings: Settings, oids: list[str]) -> list[Any]:
    # Imports stay lazy so disabled monitoring does not require initializing SNMP.
    from pysnmp.hlapi.v3arch.asyncio import (CommunityData, ContextData, ObjectIdentity,
                                             ObjectType, SnmpEngine, UdpTransportTarget, get_cmd)

    target = await UdpTransportTarget.create(
        (settings.synology_snmp_host, settings.synology_snmp_port),
        timeout=settings.synology_snmp_timeout_seconds, retries=settings.synology_snmp_retries,
    )
    engine = SnmpEngine()
    try:
        indication, status, _index, binds = await get_cmd(
            engine, CommunityData(settings.synology_snmp_community, mpModel=1), target,
            ContextData(), *(ObjectType(ObjectIdentity(oid)) for oid in oids),
        )
        if indication:
            raise TimeoutError("SNMP transport failed")
        if status:
            raise RuntimeError("SNMP response failed")
        return [value for _oid, value in binds]
    finally:
        engine.close_dispatcher()


class SynologyMonitor:
    def __init__(self, settings: Settings | None = None,
                 getter: Callable[[Settings, list[str]], Awaitable[list[Any]]] = pysnmp_get):
        self.settings = settings or get_settings()
        self._getter = getter
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._last_good: SynologySystemHealth | None = None
        self._error_category: str | None = None

    async def _get(self, oids: list[str]) -> list[Any]:
        """Apply a hard outer deadline in addition to PySNMP's UDP deadline."""
        attempts = max(0, self.settings.synology_snmp_retries) + 1
        deadline = max(0.1, self.settings.synology_snmp_timeout_seconds) * attempts + 1
        async with asyncio.timeout(deadline):
            return await self._getter(self.settings, oids)

    def snapshot(self, now: datetime | None = None) -> SynologySystemHealth:
        if not self.settings.synology_monitoring_enabled:
            return SynologySystemHealth(enabled=False, available=False, stale=False)
        now = now or datetime.now(UTC)
        if self._last_good is None:
            return SynologySystemHealth(enabled=True, available=False, stale=False,
                                        error_category=self._error_category)
        age = (now - self._last_good.last_success_at).total_seconds()
        return self._last_good.model_copy(update={
            "available": self._error_category is None,
            "stale": age > self.settings.synology_metrics_stale_seconds,
            "error_category": self._error_category,
        })

    async def poll(self) -> SynologySystemHealth:
        if not self.settings.synology_monitoring_enabled or self._lock.locked():
            return self.snapshot()
        async with self._lock:
            try:
                scalar_values = await self._get(list(SCALARS.values()))
                scalars = normalize_scalars(dict(zip(SCALARS, scalar_values)))
                disks = []
                for index in range(max(0, self.settings.synology_disk_max_index) + 1):
                    try:
                        values = await self._get(
                            [f"{oid}.{index}" for oid in DISK_COLUMNS.values()]
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # DSM installations can fail an individual absent
                        # index instead of returning NoSuchInstance varbinds.
                        # Disk discovery is best-effort; scalar health remains
                        # a valid successful sample in that case.
                        continue
                    disk = normalize_disk(index, dict(zip(DISK_COLUMNS, values)))
                    if disk:
                        disks.append(disk)
                now = datetime.now(UTC)
                self._last_good = SynologySystemHealth(
                    enabled=True, available=True, stale=False, sampled_at=now,
                    last_success_at=now, disks=tuple(disks), **scalars,
                )
                self._error_category = None
            except asyncio.CancelledError:
                raise
            except (TimeoutError, asyncio.TimeoutError):
                self._error_category = "timeout"
                logger.warning("Synology monitoring poll timed out")
            except Exception:
                self._error_category = "snmp_unavailable"
                logger.warning("Synology monitoring poll failed")
            return self.snapshot()

    async def _run(self) -> None:
        await asyncio.sleep(STARTUP_POLL_DELAY_SECONDS)
        while True:
            await self.poll()
            await asyncio.sleep(max(1, self.settings.synology_metrics_interval_seconds))

    def start(self) -> None:
        if self.settings.synology_monitoring_enabled and self._task is None:
            self._task = asyncio.create_task(self._run(), name="synology-monitor")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


synology_monitor = SynologyMonitor()


def serialize_synology_snapshot(snapshot: SynologySystemHealth | None = None) -> dict[str, Any]:
    """The only public serializer; schema fields form the privacy boundary."""
    return (snapshot or synology_monitor.snapshot()).model_dump(mode="json")
