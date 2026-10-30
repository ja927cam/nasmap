"""Small utility endpoints: place-name geocoding for the import wizard."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import CurrentUser
from ..config import settings
from ..rate_limit import auth_rate_limit

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/geocode", dependencies=[Depends(auth_rate_limit)])
async def geocode(user: CurrentUser, q: str = Query(min_length=2, max_length=200)):
    if not settings.geocoding_enabled:
        raise HTTPException(status_code=503, detail="Geocoding is disabled")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{settings.nominatim_url.rstrip('/')}/search",
                params={"q": q, "format": "jsonv2", "limit": 5, "addressdetails": 0},
                headers={"User-Agent": "NasMap/1.0 (self-hosted geospatial app)"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"Geocoding service unavailable: {exc}"
        ) from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Geocoding service returned an error")
    results = []
    for item in response.json():
        try:
            south, north, west, east = [float(v) for v in item["boundingbox"]]
        except Exception:  # noqa: BLE001
            west = south = east = north = None
        results.append(
            {
                "name": item.get("display_name"),
                "lat": float(item["lat"]) if item.get("lat") else None,
                "lon": float(item["lon"]) if item.get("lon") else None,
                "bbox": [west, south, east, north] if west is not None else None,
                "type": item.get("type"),
            }
        )
    return {"results": results}
