from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SynologyDiskHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    snmp_index: int
    id: str
    model: str | None = None
    status_code: int | None = None
    status: str = "unknown"
    temperature_c: int | None = None


class SynologySystemHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    available: bool
    stale: bool
    sampled_at: datetime | None = None
    last_success_at: datetime | None = None
    system_temperature_c: int | None = None
    cpu_percent: int | None = None
    memory_percent: int | None = None
    load_average_1m: float | None = None
    uptime_seconds: float | None = None
    thermal_status_code: int | None = None
    thermal_status: str = "unknown"
    disks: tuple[SynologyDiskHealth, ...] = ()
    error_category: str | None = Field(default=None, description="Privacy-safe failure category")
