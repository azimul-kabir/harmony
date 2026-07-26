import asyncio
from datetime import datetime, timezone
from pydantic import BaseModel, Field

import pysnmp.hlapi.asyncio as snmp

from app.core.config import get_settings
from app.core.logging import logger
from app.api.schemas.synology import SynologyDiskHealth, SynologySystemHealth

class SynologyMonitor:
    def __init__(self):
        self._task = None
        self._stop_event = asyncio.Event()
        self._snapshot = SynologySystemHealth(enabled=False)
        self._lock = asyncio.Lock()
        self._snmp_engine = snmp.SnmpEngine()

    def _get_disabled_snapshot(self):
        return SynologySystemHealth(enabled=False)

    async def get_snapshot(self) -> SynologySystemHealth:
        settings = get_settings()
        if not settings.synology_monitoring_enabled:
            return self._get_disabled_snapshot()

        async with self._lock:
            # Calculate stale state
            if self._snapshot.available and self._snapshot.last_success_at:
                try:
                    last_success = datetime.fromisoformat(self._snapshot.last_success_at)
                    stale_threshold = settings.synology_metrics_stale_seconds
                    now = datetime.now(timezone.utc)
                    if (now - last_success).total_seconds() > stale_threshold:
                        self._snapshot.stale = True
                    else:
                        self._snapshot.stale = False
                except Exception:
                    pass
            return self._snapshot.model_copy()

    def start(self):
        settings = get_settings()
        if not settings.synology_monitoring_enabled:
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Started Synology SNMP monitor.")

    async def stop(self):
        if self._task:
            self._stop_event.set()
            await self._task
            self._task = None
            logger.info("Stopped Synology SNMP monitor.")

    async def _poll_loop(self):
        settings = get_settings()
        interval = settings.synology_metrics_interval_seconds

        while not self._stop_event.is_set():
            try:
                await self._poll_snmp(settings)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in Synology monitor: {e}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _poll_snmp(self, settings):
        now_str = datetime.now(timezone.utc).isoformat()

        target = await snmp.UdpTransportTarget.create((settings.synology_snmp_host, settings.synology_snmp_port), timeout=settings.synology_snmp_timeout_seconds, retries=settings.synology_snmp_retries)
        community = snmp.CommunityData(settings.synology_snmp_community)

        # OIDs array with exact order
        oid_list = [
            snmp.ObjectType(snmp.ObjectIdentity("1.3.6.1.4.1.6574.1.2.0")), # sys_temp
            snmp.ObjectType(snmp.ObjectIdentity("1.3.6.1.4.1.6574.1.7.1.0")), # cpu_util
            snmp.ObjectType(snmp.ObjectIdentity("1.3.6.1.4.1.6574.1.7.2.0")), # mem_util
            snmp.ObjectType(snmp.ObjectIdentity("1.3.6.1.4.1.6574.1.8.0")), # thermal_status
            snmp.ObjectType(snmp.ObjectIdentity("1.3.6.1.4.1.2021.10.1.5.1")), # load_1m
            snmp.ObjectType(snmp.ObjectIdentity("1.3.6.1.2.1.25.1.1.0")), # uptime
        ]

        try:
            errorIndication, errorStatus, errorIndex, varBinds = await snmp.get_cmd(
                self._snmp_engine,
                community,
                target,
                snmp.ContextData(),
                *oid_list
            )

            if errorIndication:
                await self._handle_failure(str(errorIndication), now_str)
                return
            elif errorStatus:
                await self._handle_failure(errorStatus.prettyPrint(), now_str)
                return

            # Access sequentially by index
            sys_temp = int(varBinds[0][1])
            cpu_util = int(varBinds[1][1])
            mem_util = int(varBinds[2][1])
            thermal_status_code = int(varBinds[3][1])
            thermal_status_str = "Normal" if thermal_status_code == 1 else "Failed"

            # load average is divided by 100
            load_raw = varBinds[4][1]
            load_1m = None
            if load_raw:
                try:
                    # In pySNMP, OctetString can be parsed or int. Try float.
                    if hasattr(load_raw, 'asNumbers'):
                        load_str = load_raw.prettyPrint()
                        load_1m = float(load_str) / 100.0 if load_str else None
                    else:
                        load_1m = float(load_raw) / 100.0
                except (ValueError, TypeError):
                    load_str = load_raw.prettyPrint()
                    try:
                        load_1m = float(load_str) / 100.0
                    except ValueError:
                        pass

            uptime_ticks = int(varBinds[5][1])
            uptime_seconds = uptime_ticks / 100.0

            # Disk Probing
            disks = await self._probe_disks(self._snmp_engine, community, target, settings.synology_disk_max_index)

            async with self._lock:
                self._snapshot = SynologySystemHealth(
                    enabled=True,
                    available=True,
                    stale=False,
                    sampled_at=now_str,
                    last_success_at=now_str,
                    system_temperature_c=sys_temp,
                    cpu_percent=cpu_util,
                    memory_percent=mem_util,
                    load_average_1m=load_1m,
                    uptime_seconds=uptime_seconds,
                    thermal_status_code=thermal_status_code,
                    thermal_status=thermal_status_str,
                    disks=disks,
                    safe_error_category=None
                )

        except Exception as e:
            await self._handle_failure("Unexpected SNMP error", now_str)
            logger.debug(f"SNMP Poll Exception: {e}")

    async def _handle_failure(self, error_msg: str, now_str: str):
        safe_error = "Timeout" if "timeout" in error_msg.lower() else "ConnectionError"
        async with self._lock:
            # Preserve last success values, update availability and error
            current = self._snapshot
            self._snapshot = SynologySystemHealth(
                enabled=True,
                available=False,
                stale=current.stale,
                sampled_at=now_str,
                last_success_at=current.last_success_at,
                system_temperature_c=current.system_temperature_c,
                cpu_percent=current.cpu_percent,
                memory_percent=current.memory_percent,
                load_average_1m=current.load_average_1m,
                uptime_seconds=current.uptime_seconds,
                thermal_status_code=current.thermal_status_code,
                thermal_status=current.thermal_status,
                disks=current.disks,
                safe_error_category=safe_error
            )

    async def _probe_disks(self, snmp_engine, community, target, max_index) -> list[SynologyDiskHealth]:
        disks = []
        for i in range(max_index + 1):
            disk_oids = [
                snmp.ObjectType(snmp.ObjectIdentity(f"1.3.6.1.4.1.6574.2.1.1.2.{i}")), # ID
                snmp.ObjectType(snmp.ObjectIdentity(f"1.3.6.1.4.1.6574.2.1.1.3.{i}")), # Model
                snmp.ObjectType(snmp.ObjectIdentity(f"1.3.6.1.4.1.6574.2.1.1.5.{i}")), # Status
                snmp.ObjectType(snmp.ObjectIdentity(f"1.3.6.1.4.1.6574.2.1.1.6.{i}")), # Temperature
            ]

            errorIndication, errorStatus, errorIndex, varBinds = await snmp.get_cmd(
                snmp_engine,
                community,
                target,
                snmp.ContextData(),
                *disk_oids
            )

            if errorIndication or errorStatus:
                continue

            try:
                # Check for NoSuchInstance/NoSuchObject
                if any(v[1].__class__.__name__ in ("NoSuchInstance", "NoSuchObject") for v in varBinds):
                    continue

                disk_id = varBinds[0][1].prettyPrint()
                if not disk_id:
                    continue

                model = varBinds[1][1].prettyPrint()
                status_code = int(varBinds[2][1])
                status_str = "Normal" if status_code == 1 else "Failed" # Simplified status

                temp_raw = varBinds[3][1]
                temp_c = None
                try:
                    temp_c = int(temp_raw)
                except ValueError:
                    pass

                disks.append(SynologyDiskHealth(
                    snmp_index=i,
                    id=disk_id,
                    model=model,
                    status_code=status_code,
                    status=status_str,
                    temperature_c=temp_c
                ))
            except Exception:
                continue

        return disks

synology_monitor = SynologyMonitor()
