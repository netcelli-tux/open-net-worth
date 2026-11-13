"""Manual fetch-and-book (services.connector_book): books new rows with no model, holds back
what looks like an existing transaction, skips unlinked accounts, and is idempotent."""

from __future__ import annotations

from datetime import timedelta

import pytest

from backend.core.errors import ValidationError
from backend.core.user_time import user_today
from backend.services import accounts as accounts_service
from backend.services import connector_book, connector_fetch, ledger


@pytest.fixture(autouse=True)
def isolate(db_isolated):
    pass


def _account() -> str:
    return accounts_service.create_account(
        {
            "name": "Everyday",
            "type": "cash",
            "currency": ledger.base_currency(),
            "initial_balance": 0,
            "initial_balance_date": "2026-01-01",
        }
    )["id"]


def _fake_fetch(rows):
    """Serves only the rows inside the requested window, like the real provider."""

    def fetch(provider_key, *, since, before, **_):
        return {
            "status": "ok",
            "error": None,
            "window": {"since": since, "before": before, "complete": True},
            "transactions": [r for r in rows if since <= r["date"] <= before],
            "counts": {"already_booked": 0, "pending_skipped": 0, "truncated": False},
        }

    return fetch


def _row(ref, amount, linked, description="Acme Coffee", day=None):
    return {
        "external_refs": [{"source": "lunch_flow_personal", "ref": ref}],
        "date": day or (user_today() - timedelta(days=3)).isoformat(),
        "amount": amount,
        "currency": ledger.base_currency(),
        "description": description,
        "memo": None,
        "linked_account_id": linked,
    }


def test_books_new_rows_skips_unlinked_and_is_idempotent(monkeypatch):
    acct = _account()
    rows = [
        _row("7:a", -12.5, acct),
        _row("7:b", 100.0, acct, "Acme Payroll"),
        _row("8:c", -3, None),
    ]
    monkeypatch.setattr(connector_fetch, "fetch", _fake_fetch(rows))

    out = connector_book.fetch_and_book("lunch_flow_personal")
    assert (out["booked"], out["unlinked"], out["held_for_review"]) == (2, 1, [])
    assert out["batch_id"]
    live = [t for t in ledger.transactions.query(batch_id=out["batch_id"]) if not t.get("deleted")]
    booked = {t["description"]: t for t in live}
    assert booked["Acme Coffee"]["kind"] == "expense"
    assert booked["Acme Payroll"]["kind"] == "income"

    again = connector_book.fetch_and_book("lunch_flow_personal")
    assert again["booked"] == 0  # same refs: the L0 floor refuses a second copy


def test_a_row_matching_a_hand_entry_is_held_not_booked(monkeypatch):
    acct = _account()
    ledger.create_transaction(
        {
            "date": (user_today() - timedelta(days=3)).isoformat(),
            "kind": "expense",
            "description": "Acme Coffee",
            "from_account_id": acct,
            "from_amount": 12.5,
            "from_currency": ledger.base_currency(),
            "source": "manual",
        }
    )
    monkeypatch.setattr(connector_fetch, "fetch", _fake_fetch([_row("7:a", -12.5, acct)]))
    out = connector_book.fetch_and_book("lunch_flow_personal")
    assert out["booked"] == 0 and len(out["held_for_review"]) == 1


def test_other_connectors_are_refused():
    with pytest.raises(ValidationError):
        connector_book.fetch_and_book("plaid")


def test_a_long_history_books_in_one_run(monkeypatch):
    """600 rows over three months: more than one fetch's worth, all booked by one click."""
    from datetime import date

    acct = _account()
    start = date(2026, 8, 15)
    rows = [
        _row(f"7:{i}", -(i + 1), acct, f"Acme {i}", (start + timedelta(days=i % 90)).isoformat())
        for i in range(600)
    ]
    monkeypatch.setattr(connector_fetch, "fetch", _fake_fetch(rows))
    monkeypatch.setattr(
        connector_book.matching,
        "match_batch",
        lambda drafts, **_: [connector_book.matching.RowMatch(index=i) for i in range(len(drafts))],
    )

    out = connector_book.fetch_and_book("lunch_flow_personal", since="2026-08-15")
    assert out["booked"] == 600 and out["more_to_fetch"] is False
    assert len(ledger.transactions.query(batch_id=out["batch_id"])) == 600
