from fastapi import APIRouter

from app.providers.metadata.registry import all_providers

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("/capabilities")
def capabilities():
    return {"providers": [provider.capabilities.__dict__ for provider in all_providers().values()]}


@router.get("/status")
def status():
    return {"providers": [provider.status() for provider in all_providers().values()]}
