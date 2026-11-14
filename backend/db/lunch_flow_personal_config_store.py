"""LunchFlowPersonalConfigStore — config + fetch state for the Lunch Flow Personal API connector.

A facade over the ``lunch_flow_personal`` row of ``ConnectorStore`` (see
``AggregatorConfigStore``). The one credential is an **API key** the user copies from an API
destination in their own Lunch Flow dashboard; it lives in ``connector_secrets`` and is never
returned by ``public()`` (only ``has_api_key``). A blank ``api_key`` on update means "leave the
saved one unchanged" (write-only).

Data-only repository — the protocol lives in ``services/aggregation/lunch_flow_personal.py``.
"""

from __future__ import annotations

from backend.db.aggregator_config_store import AggregatorConfigStore

DEFAULTS: dict = {
    "enabled": False,
    "api_key": "",  # WRITE-ONLY — never returned to the frontend
    "last_synced_at": None,
    "last_status": "never_run",  # never_run | ok | auth_error | connect_error | rate_limited | error
    "last_error": None,
    "last_caution": None,  # the polarity smell test's advisory, shared with Lunch Flow
}


class LunchFlowPersonalConfigStore(AggregatorConfigStore):
    KIND = "lunch_flow_personal"
    LABEL = "Lunch Flow Personal"
    DEFAULTS = DEFAULTS
    SECRET_KEYS = ("api_key",)
    STATE_KEYS = ("last_synced_at", "last_status", "last_error", "last_caution")

    def api_key(self) -> str:
        return (self.get().get("api_key") or "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key())

    def public(self) -> dict:
        cfg = self.get()
        return {
            "configured": self.is_configured(),
            "enabled": cfg["enabled"],
            "has_api_key": bool((cfg.get("api_key") or "").strip()),
            "last_synced_at": cfg["last_synced_at"],
            "last_status": cfg["last_status"],
            "last_error": cfg["last_error"],
            "last_caution": cfg.get("last_caution"),
        }
