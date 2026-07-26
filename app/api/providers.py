from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.providers.metadata.errors import ProviderError
from app.providers.metadata.registry import all_providers, get_provider

router = APIRouter(prefix="/api/providers", tags=["providers", "development"])


class SearchRequest(BaseModel):
    provider: str = "musicbrainz"
    entity_type: Literal["recording", "release", "artist"]
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    force_refresh: bool = False
    bypass_cache: bool = False


class LookupRequest(BaseModel):
    provider: str = "musicbrainz"
    entity_type: Literal["recording", "release", "release_group", "artist"]
    entity_id: str = Field(min_length=1, max_length=255)
    force_refresh: bool = False
    bypass_cache: bool = False


def _provider(name: str):
    try: return get_provider(name)
    except KeyError: return None


def _error(exc: ProviderError) -> JSONResponse:
    status = 499 if exc.code == "cancelled" else 404 if exc.code == "not_found" else 400 if exc.code == "validation_failure" else 503 if exc.code == "not_configured" else 504 if exc.code == "timeout" else 502
    return JSONResponse(status_code=status, content={"error": {"code": exc.code, "message": exc.message,
        "provider": exc.provider, "operation": exc.operation, "retryable": exc.retryable}})


@router.get("/capabilities")
def capabilities():
    return {"providers": [provider.capabilities.__dict__ for provider in all_providers().values()]}


@router.get("/status")
def status():
    return {"providers": [provider.status() for provider in all_providers().values()]}


@router.post("/test-search")
async def test_search(body: SearchRequest):
    provider = _provider(body.provider)
    if provider is None: return JSONResponse(status_code=404, content={"error": {"code": "provider_not_found", "message": "Provider not found"}})
    try:
        return await provider.search(body.entity_type, body.query, limit=body.limit, offset=body.offset,
            force_refresh=body.force_refresh, bypass_cache=body.bypass_cache)
    except ProviderError as exc: return _error(exc)


@router.post("/lookup")
async def lookup(body: LookupRequest):
    provider = _provider(body.provider)
    if provider is None: return JSONResponse(status_code=404, content={"error": {"code": "provider_not_found", "message": "Provider not found"}})
    try:
        return await provider.lookup(body.entity_type, body.entity_id,
            force_refresh=body.force_refresh, bypass_cache=body.bypass_cache)
    except ProviderError as exc: return _error(exc)
