"""Lunch Flow Personal API provider — protocol + normalization, with httpx mocked (no network)."""

from __future__ import annotations

import httpx
import pytest

from backend.api.lunch_flow_personal_api import (
    LunchFlowPersonalConfigUpdate,
    update_lunch_flow_personal_config,
)
from backend.core.errors import ExternalServiceError, ValidationError
from backend.db.lunch_flow_personal_config_store import LunchFlowPersonalConfigStore
from backend.services.aggregation import lunch_flow_personal as svc

_ACCOUNTS = {"accounts": [{"id": 7, "name": "Everyday", "currency": "gbp"}], "total": 1}
_TXNS = {
    "transactions": [
        {
            "id": "tx_1",
            "accountId": 7,
            "amount": -12.5,
            "currency": "GBP",
            "date": "2026-10-01",
            "merchant": "Acme Coffee",
            "isPending": False,
        },
        {
            "id": "tx_2",
            "accountId": 7,
            "amount": 100,
            "currency": "GBP",
            "date": "2026-09-01",
            "merchant": "Too early",
            "isPending": False,
        },
    ],
    "total": 2,
}


@pytest.fixture(autouse=True)
def isolate_store(db_isolated):
    pass


def _mock(monkeypatch, status=200):
    calls: list[dict] = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params, "headers": headers})
        body = _TXNS if url.endswith("/transactions") else _ACCOUNTS
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(svc.httpx, "get", fake_get)
    return calls


def _store() -> LunchFlowPersonalConfigStore:
    update_lunch_flow_personal_config(LunchFlowPersonalConfigUpdate(api_key="lfp-key"))
    return LunchFlowPersonalConfigStore()


def test_fetch_sends_the_key_and_window_and_maps_rows(monkeypatch):
    calls = _mock(monkeypatch)
    win = svc.fetch_window(_store(), "2026-09-15", "2026-10-15", None)

    assert calls[0]["url"] == "https://www.lunchflow.app/api/v1/accounts"
    assert all(c["headers"]["x-api-key"] == "lfp-key" for c in calls)
    assert calls[1]["params"] == {"from": "2026-09-15", "to": "2026-10-15"}
    assert win.accounts == [
        {
            "provider_account_id": "7",
            "name": "Everyday",
            "mask": None,
            "currency": "GBP",
            "balance": None,
        }
    ]
    # tx_2 is outside the window: dropped even though the server returned it.
    [row] = win.rows
    assert row["external_refs"] == [{"source": "lunch_flow_personal", "ref": "7:tx_1"}]
    assert (row["amount"], row["currency"], row["description"]) == (-12.5, "GBP", "Acme Coffee")


def test_accounts_only_makes_no_transaction_call(monkeypatch):
    calls = _mock(monkeypatch)
    win = svc.fetch_window(_store(), "2026-09-15", "2026-10-15", None, accounts_only=True)
    assert len(calls) == 1 and win.rows == [] and len(win.accounts) == 1


def test_bad_key_is_an_auth_error_and_never_leaks_the_key(monkeypatch):
    _mock(monkeypatch, status=401)
    with pytest.raises(ExternalServiceError) as exc:
        svc.fetch_window(_store(), "2026-09-15", "2026-10-15", None)
    assert svc.classify_error(exc.value) == "auth_error"
    assert "lfp-key" not in str(exc.value)


def test_no_key_refuses_before_any_request(monkeypatch):
    calls = _mock(monkeypatch)
    with pytest.raises(ValidationError):
        svc.fetch_window(LunchFlowPersonalConfigStore(), "2026-09-15", "2026-10-15", None)
    assert calls == []


def test_saving_a_key_enables_and_status_hides_it():
    status = update_lunch_flow_personal_config(LunchFlowPersonalConfigUpdate(api_key="lfp-key"))
    assert status["enabled"] is True and status["has_api_key"] is True
    assert "lfp-key" not in str(status)
