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
def isolate(db_isolated, monkeypatch):
    _bank(monkeypatch, {})  # no bank balances unless a test says so


def _bank(monkeypatch, balances: dict[str, float]):
    """The provider's account listing: one entry per linked account id, with its balance."""
    monkeypatch.setattr(
        connector_fetch,
        "provider_accounts",
        lambda key: {
            "accounts": [
                {"linked_account_id": a, "balance": b, "currency": ledger.base_currency()}
                for a, b in balances.items()
            ]
        },
    )


def _account(type_: str = "cash", start: str = "2026-01-01") -> str:
    return accounts_service.create_account(
        {
            "name": "Everyday",
            "type": type_,
            "currency": ledger.base_currency(),
            "initial_balance": 0,
            "initial_balance_date": start,
        }
    )["id"]


def _balance(account_id: str) -> float:
    acct = ledger.accounts.find_by_id(account_id)
    txns = ledger.transactions.all()
    return ledger.account_balance(acct, txns, ledger.opening_date(acct, txns))


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


def test_history_counts_and_the_balance_matches_the_bank(monkeypatch):
    """Rows older than the account's start move the start back (balance-preserving), then one
    adjustment sets the balance to the bank's — and such a run is not offered for undo."""
    yesterday = (user_today() - timedelta(days=1)).isoformat()
    ten_days_ago = (user_today() - timedelta(days=10)).isoformat()
    acct = _account(start=yesterday)
    monkeypatch.setattr(
        connector_fetch, "fetch", _fake_fetch([_row("7:old", -20.0, acct, "Acme", ten_days_ago)])
    )
    _bank(monkeypatch, {acct: 500.0})

    out = connector_book.fetch_and_book("lunch_flow_personal")

    [note] = out["balances"]
    assert note["start_moved_to"] == ten_days_ago
    acct_row = ledger.accounts.find_by_id(acct)
    assert ledger.opening_date(acct_row, ledger.transactions.all()) == ten_days_ago
    assert note["adjusted_by"] == 500.0
    assert _balance(acct) == 500.0
    assert out["undoable"] is False


def test_a_card_with_a_positive_bank_balance_is_not_matched(monkeypatch):
    card = _account("credit")
    monkeypatch.setattr(connector_fetch, "fetch", _fake_fetch([_row("7:c", -30.0, card)]))
    _bank(monkeypatch, {card: 250.0})

    out = connector_book.fetch_and_book("lunch_flow_personal")

    assert "positive card balance" in out["balances"][0]["not_matched"]
    assert _balance(card) == -30.0


def test_a_run_that_only_booked_rows_can_be_undone(monkeypatch):
    acct = _account()
    monkeypatch.setattr(connector_fetch, "fetch", _fake_fetch([_row("7:u", -12.5, acct)]))
    _bank(monkeypatch, {acct: -12.5})  # already equal: no adjustment

    out = connector_book.fetch_and_book("lunch_flow_personal")

    assert out["balances"][0]["adjusted_by"] == 0.0
    assert out["undoable"] is True
