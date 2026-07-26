from fastapi import APIRouter
from app.api.schemas.synology import SynologySystemHealth
from app.services.synology_monitor import synology_monitor

router = APIRouter(
    prefix="/api/system-health/synology",
    tags=["system-health"],
)

@router.get("", response_model=SynologySystemHealth)
async def get_synology_health():
    """Returns the current Synology SNMP monitoring snapshot."""
    return await synology_monitor.get_snapshot()
