import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.synology_monitor import synology_monitor, SynologyMonitor
from app.api.schemas.synology import SynologySystemHealth, SynologyDiskHealth
from app.core.config import get_settings

@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param

@pytest.fixture
def mock_settings():
    settings = get_settings()
    settings.synology_monitoring_enabled = True
    settings.synology_snmp_host = "127.0.0.1"
    settings.synology_metrics_interval_seconds = 1
    settings.synology_disk_max_index = 2
    return settings

@pytest.mark.anyio
async def test_synology_disabled_snapshot(mock_settings):
    mock_settings.synology_monitoring_enabled = False

    snapshot = await synology_monitor.get_snapshot()
    assert snapshot.enabled is False
    assert snapshot.available is False

@pytest.mark.anyio
async def test_synology_stale_state(mock_settings):
    monitor = SynologyMonitor()
    # Mock an old success
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
    monitor._snapshot = SynologySystemHealth(
        enabled=True,
        available=True,
        last_success_at=old_time,
        stale=False
    )

    mock_settings.synology_metrics_stale_seconds = 120

    with patch("app.services.synology_monitor.get_settings", return_value=mock_settings):
        snapshot = await monitor.get_snapshot()
        assert snapshot.stale is True

@pytest.mark.anyio
async def test_snmp_failure_keeps_last_good_data(mock_settings):
    monitor = SynologyMonitor()
    monitor._snapshot = SynologySystemHealth(
        enabled=True,
        available=True,
        last_success_at="2024-01-01T12:00:00Z",
        system_temperature_c=40,
        cpu_percent=10
    )

    with patch("app.services.synology_monitor.snmp.get_cmd", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = (None, MagicMock(prettyPrint=lambda: "timeout"), 0, [])
        await monitor._poll_snmp(mock_settings)

        snapshot = monitor._snapshot
        assert snapshot.available is False
        assert snapshot.system_temperature_c == 40 # Retained
        assert snapshot.cpu_percent == 10 # Retained
        assert snapshot.safe_error_category in ("Timeout", "ConnectionError")

@pytest.mark.anyio
async def test_snmp_success_normalization(mock_settings):
    monitor = SynologyMonitor()

    # Mocking varBinds for scalars
    def make_varbind(oid, val, is_obj=False):
        v = MagicMock()
        v.prettyPrint.return_value = str(val) if not is_obj else val
        if not is_obj:
            v.__int__ = lambda s: int(val)
        return (MagicMock(prettyPrint=lambda: oid), v)

    varBinds = [
        make_varbind("1.3.6.1.4.1.6574.1.2.0", 42), # Temp
        make_varbind("1.3.6.1.4.1.6574.1.7.1.0", 15), # CPU
        make_varbind("1.3.6.1.4.1.6574.1.7.2.0", 55), # Mem
        make_varbind("1.3.6.1.4.1.6574.1.8.0", 1), # Thermal
        make_varbind("1.3.6.1.4.1.2021.10.1.5.1", 123), # Load
        make_varbind("1.3.6.1.2.1.25.1.1.0", 8640000), # Uptime ticks (1 day)
    ]

    with patch("app.services.synology_monitor.snmp.get_cmd", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = (None, None, 0, varBinds)

        # Mock probe disks to return empty list
        with patch.object(monitor, "_probe_disks", new_callable=AsyncMock) as mock_probe:
            mock_probe.return_value = []

            await monitor._poll_snmp(mock_settings)

            snapshot = monitor._snapshot
            assert snapshot.available is True
            assert snapshot.system_temperature_c == 42
            assert snapshot.cpu_percent == 15
            assert snapshot.memory_percent == 55
            assert snapshot.thermal_status_code == 1
            assert snapshot.thermal_status == "Normal"
            assert snapshot.load_average_1m == 1.23 # Divided by 100
            assert snapshot.uptime_seconds == 86400.0 # Divided by 100

@pytest.mark.anyio
async def test_disk_probing():
    monitor = SynologyMonitor()
    mock_settings = MagicMock()
    mock_settings.synology_disk_max_index = 1

    # Mocking varBinds for disks
    def make_varbind(val, is_no_such=False):
        v = MagicMock()
        v.prettyPrint.return_value = val
        if is_no_such:
            v.__class__.__name__ = "NoSuchInstance"
        else:
            v.__class__.__name__ = "Integer"
        v.__int__ = lambda self: int(val) if val.isdigit() else 0
        return (MagicMock(), v)

    # Responses:
    # Disk 0: valid
    disk_0_resp = (None, None, 0, [
        make_varbind("Disk 1"), # ID
        make_varbind("WD1000"), # Model
        make_varbind("1"), # Status
        make_varbind("35"), # Temp
    ])

    # Disk 1: Missing
    disk_1_resp = (None, None, 0, [
        make_varbind("", is_no_such=True),
        make_varbind("", is_no_such=True),
        make_varbind("", is_no_such=True),
        make_varbind("", is_no_such=True),
    ])

    with patch("app.services.synology_monitor.snmp.get_cmd", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [disk_0_resp, disk_1_resp]

        disks = await monitor._probe_disks(None, None, None, 1)

        assert len(disks) == 1
        assert disks[0].id == "Disk 1"
        assert disks[0].model == "WD1000"
        assert disks[0].status_code == 1
        assert disks[0].status == "Normal"
        assert disks[0].temperature_c == 35
