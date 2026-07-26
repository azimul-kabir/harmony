from pydantic import BaseModel, Field

class SynologyDiskHealth(BaseModel):
    snmp_index: int
    id: str
    model: str
    status_code: int
    status: str
    temperature_c: int | None = None

class SynologySystemHealth(BaseModel):
    enabled: bool = False
    available: bool = False
    stale: bool = False
    sampled_at: str | None = None
    last_success_at: str | None = None
    system_temperature_c: int | None = None
    cpu_percent: int | None = None
    memory_percent: int | None = None
    load_average_1m: float | None = None
    uptime_seconds: float | None = None
    thermal_status_code: int | None = None
    thermal_status: str | None = None
    disks: list[SynologyDiskHealth] = Field(default_factory=list)
    safe_error_category: str | None = None
