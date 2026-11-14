"""Lunch Flow Personal API connector REST — the API key and the on/off switch.

* ``GET /api/lunch-flow-personal/status`` — public config + stats (only ``has_api_key``).
* ``PUT /api/lunch-flow-personal/config`` — set the API key (blank keeps the saved one).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.db.lunch_flow_personal_config_store import LunchFlowPersonalConfigStore

router = APIRouter()


class LunchFlowPersonalConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("/api/lunch-flow-personal/status")
def lunch_flow_personal_status():
    return LunchFlowPersonalConfigStore().public()


@router.put("/api/lunch-flow-personal/config")
def update_lunch_flow_personal_config(body: LunchFlowPersonalConfigUpdate):
    """A non-blank key is saved as-is (an invalid one surfaces on the next fetch as
    ``auth_error``) and, unless ``enabled`` is given, turns the connector on."""
    store = LunchFlowPersonalConfigStore()
    changes: dict = {}
    key = (body.api_key or "").strip()
    if key:
        changes["api_key"] = key
        if body.enabled is None:
            changes["enabled"] = True
    if body.enabled is not None:
        changes["enabled"] = bool(body.enabled)
    store.update(changes)
    return store.public()
