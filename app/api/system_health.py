from fastapi import APIRouter

from app.api.schemas.system_health import SynologySystemHealth
from app.services.synology_monitor import serialize_synology_snapshot, synology_monitor

router = APIRouter(prefix="/api/system-health", tags=["system-health"])


@router.get("/synology", response_model=SynologySystemHealth)
def synology_health():
    return serialize_synology_snapshot(synology_monitor.snapshot())
