"""Lunch Flow Personal API connector REST — the API key and the on/off switch.

* ``GET /api/lunch-flow-personal/status`` — public config + stats (only ``has_api_key``).
* ``PUT /api/lunch-flow-personal/config`` — set the API key (blank keeps the saved one).
* ``POST /api/lunch-flow-personal/fetch-and-book`` — fetch and book new transactions with no
  model in the loop (``services.connector_book``); Lucius's fetch tool still works too.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.errors import OpenNetWorthError, to_http_status
from backend.db.lunch_flow_personal_config_store import LunchFlowPersonalConfigStore
from backend.services import connector_book

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


class FetchAndBookRequest(BaseModel):
    since: Optional[str] = None  # YYYY-MM-DD; omitted = the connector's usual window


@router.post("/api/lunch-flow-personal/fetch-and-book")
def lunch_flow_personal_fetch_and_book(body: FetchAndBookRequest):
    try:
        return connector_book.fetch_and_book("lunch_flow_personal", since=body.since)
    except OpenNetWorthError as exc:
        raise HTTPException(to_http_status(exc), exc.message or str(exc)) from exc
