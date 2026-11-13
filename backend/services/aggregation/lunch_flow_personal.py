"""Lunch Flow Personal API provider — read your OWN Lunch Flow accounts with one API key.

Lunch Flow's Personal API (https://www.lunchflow.app/docs/api/personal-api-overview, base
``https://www.lunchflow.app/api/v1``) is the single-key sibling of the restricted Platform API the
``lunch_flow`` connector uses. The key comes from an API destination in the user's own Lunch
Flow dashboard and is sent as ``x-api-key`` on every request:

  * ``GET /accounts`` → ``{accounts: [{id, name, institution_name, currency, ...}], total}``
  * ``GET /accounts/{id}/transactions?from=&to=`` → ``{transactions: [...], total}`` — the SAME
    transaction shape as the Platform API, so rows are mapped by ``lunch_flow._txn_to_row``
    (sign convention, description, ref) under this connector's own ref namespace.

Pending rows stay out (``include_pending`` defaults to false server-side). READ-ONLY: called
from a Lucius turn via ``lunch_flow_personal_fetch_transactions``; booking happens through
``add_transactions``, never here. Errors carry the status code only — never the key or URL.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from backend.core.errors import ExternalServiceError, ValidationError
from backend.db.lunch_flow_personal_config_store import LunchFlowPersonalConfigStore
from backend.services import ledger as ledger_service
from backend.services.aggregation.lunch_flow import (
    _account_to_common,
    _polarity_smell_test,
    _txn_to_row,
)
from backend.services.aggregation.providers import FetchWindow

logger = logging.getLogger(__name__)

EXTERNAL_SOURCE = "lunch_flow_personal"
# The bare lunchflow.app 308s here; pinned rather than following redirects, which would
# hand the x-api-key header to whatever host a redirect names.
API_BASE = "https://www.lunchflow.app/api/v1"
_HTTP_TIMEOUT = 30.0
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def _get(store: LunchFlowPersonalConfigStore, path: str, params: Optional[dict] = None) -> dict:
    key = store.api_key()
    if not key:
        raise ValidationError("Lunch Flow Personal is not configured (no API key)")
    try:
        resp = httpx.get(
            f"{API_BASE}{path}",
            params=params,
            headers={"x-api-key": key, "Accept": "application/json"},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ExternalServiceError(f"Lunch Flow HTTP {exc.response.status_code}") from None
    except Exception as exc:  # a non-httpx error (e.g. a non-ASCII key) must not leak the key
        raise ExternalServiceError(f"Lunch Flow request failed ({type(exc).__name__})") from None
    if len(resp.content) > _MAX_RESPONSE_BYTES:
        raise ExternalServiceError("Lunch Flow response too large; refused.")
    return resp.json() or {}


def fetch_window(
    store: LunchFlowPersonalConfigStore,
    since: str,
    before: str,
    account: Optional[str],
    *,
    accounts_only: bool = False,
) -> FetchWindow:
    """Every account the key sees, plus each one's transactions in ``[since, before]`` (the
    window is passed server-side as ``from``/``to``). A per-account failure skips that account;
    a 401/403 on any call fails the whole fetch as ``auth_error``."""
    lf_accounts = [
        a for a in (_get(store, "/accounts").get("accounts") or []) if isinstance(a, dict)
    ]
    if account:
        lf_accounts = [a for a in lf_accounts if str(a.get("id")) == account]
    accounts = [_account_to_common(a) for a in lf_accounts]

    rows: list[dict] = []
    income = expense = 0
    for lf_account in [] if accounts_only else lf_accounts:
        account_id = lf_account.get("id")
        if account_id is None:
            continue
        try:
            data = _get(
                store, f"/accounts/{account_id}/transactions", {"from": since, "to": before}
            )
        except ExternalServiceError as exc:
            if classify_error(exc) == "auth_error":
                raise
            logger.warning("lunch_flow_personal account fetch failed (%s): %s", account_id, exc)
            continue
        hint = (lf_account.get("currency") or ledger_service.base_currency()).upper()
        for lf_txn in data.get("transactions") or []:
            if not isinstance(lf_txn, dict):
                continue
            row = _txn_to_row(lf_txn, str(account_id), hint, EXTERNAL_SOURCE)
            # The server filters by date already; this guards a server that ignores from/to.
            if row is None or not (since <= row["date"] <= before):
                continue
            rows.append(row)
            if not row["pending"]:
                income, expense = (
                    (income + 1, expense) if row["amount"] > 0 else (income, expense + 1)
                )

    caution = _polarity_smell_test(income, expense)
    return FetchWindow(
        accounts=accounts, rows=rows, complete=True, warnings=[caution] if caution else []
    )


def classify_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "auth_error"
    if isinstance(exc, ExternalServiceError):
        msg = str(exc)
        if "HTTP 401" in msg or "HTTP 403" in msg:
            return "auth_error"
        if "HTTP 429" in msg:
            return "rate_limited"
        return "connect_error"
    if isinstance(exc, httpx.HTTPError):
        return "connect_error"
    return "error"
