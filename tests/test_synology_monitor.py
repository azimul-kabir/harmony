import asyncio
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.api.system_health import synology_health
from app.services.synology_monitor import (
    DISK_COLUMNS, SCALARS, SynologyMonitor, normalize_disk, normalize_scalars,
    serialize_synology_snapshot,
)


def settings(**overrides):
    return Settings(
        synology_monitoring_enabled=True, synology_snmp_host="nas",
        synology_snmp_community="do-not-leak", synology_disk_max_index=3,
        **overrides,
    )


def test_scalar_normalization_and_status_mapping():
    result = normalize_scalars(dict(zip(SCALARS, [42, 19, 61, 1, 123, 98765])))
    assert result == {
        "system_temperature_c": 42, "cpu_percent": 19, "memory_percent": 61,
        "thermal_status_code": 1, "load_average_1m": 1.23,
        "uptime_seconds": 987.65, "thermal_status": "normal",
    }
    assert normalize_scalars({"thermal_status_code": 2})["thermal_status"] == "failed"


def test_disk_uses_returned_id_and_handles_partial_invalid_rows():
    disk = normalize_disk(0, {"id": "Disk 2", "model": "WD", "status_code": "1", "temperature_c": "bad"})
    assert disk.id == "Disk 2"
    assert disk.snmp_index == 0
    assert disk.temperature_c is None
    assert normalize_disk(1, {"id": "No Such Instance currently exists"}) is None
    partial = normalize_disk(2, {"id": "Disk 7"})
    assert partial.model is None and partial.status == "unknown"


def test_indexed_get_probes_zero_through_configured_max_and_ignores_missing():
    calls = []

    async def getter(_settings, oids):
        calls.append(oids)
        if oids == list(SCALARS.values()):
            return [40, 10, 20, 1, 50, 100]
        index = int(oids[0].rsplit(".", 1)[1])
        return (["Disk 9", "Model", 1, 38] if index == 2
                else ["No Such Instance currently exists", None, None, None])

    monitor = SynologyMonitor(settings(), getter)
    snapshot = asyncio.run(monitor.poll())
    assert [disk.id for disk in snapshot.disks] == ["Disk 9"]
    assert [int(call[0].rsplit(".", 1)[1]) for call in calls[1:]] == [0, 1, 2, 3]
    assert all(len(call) == len(DISK_COLUMNS) for call in calls[1:])


def test_failure_retains_last_good_and_stale_is_calculated():
    should_fail = False

    async def getter(_settings, oids):
        if should_fail:
            raise TimeoutError
        if oids == list(SCALARS.values()):
            return [40, 10, 20, 1, 50, 100]
        return ["No Such Instance currently exists", None, None, None]

    monitor = SynologyMonitor(settings(synology_metrics_stale_seconds=5), getter)
    good = asyncio.run(monitor.poll())
    should_fail = True
    failed = asyncio.run(monitor.poll())
    assert not failed.available and failed.error_category == "timeout"
    assert failed.system_temperature_c == good.system_temperature_c
    stale = monitor.snapshot(good.last_success_at + timedelta(seconds=6))
    assert stale.stale and stale.last_success_at == good.last_success_at


def test_disabled_snapshot_and_safe_serializer():
    monitor = SynologyMonitor(Settings(synology_monitoring_enabled=False))
    snapshot = asyncio.run(monitor.poll())
    assert snapshot.enabled is False and snapshot.available is False
    payload = serialize_synology_snapshot(snapshot)
    encoded = str(payload)
    assert "community" not in encoded and "do-not-leak" not in encoded
    assert set(payload) == {
        "enabled", "available", "stale", "sampled_at", "last_success_at",
        "system_temperature_c", "cpu_percent", "memory_percent", "load_average_1m",
        "uptime_seconds", "thermal_status_code", "thermal_status", "disks", "error_category",
    }


def test_api_returns_normalized_privacy_safe_shape():
    encoded = str(synology_health()).lower()
    assert "community" not in encoded
    assert "traceback" not in encoded


def test_dashboard_supports_dynamic_disk_counts_with_safe_dom():
    source = open("app/static/js/dashboard.js", encoding="utf-8").read()
    assert "rows.forEach" in source
    assert "document.createElement" in source
    assert ".textContent" in source
    assert "Disk 1" not in source and "Disk 2" not in source
