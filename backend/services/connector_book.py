"""Fetch and book a connector's new transactions with no model in the loop (ADR
2026-09-05-connectors-are-data-sources-lucius-books, 2026-11-13 amendment).

The deterministic counterpart of a Lucius sync turn, for the connectors in ``MANUAL_BOOK``:
``connector_fetch.fetch`` (new, posted rows only), then ``ledger.bulk_create_transactions``
with the L0 ref floor, as ONE import batch so the whole run can be rolled back. What a model
would have JUDGED is left out instead: a row the match engine pairs with an existing
transaction (``strong``/``review``) is held back and listed, never booked or linked, and a row
on an unlinked provider account is counted, never guessed onto an account. Categories are left
blank for the user or their Automations, as on every connector.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from typing import Optional

from backend.core import audit_context, data_events
from backend.core.errors import OpenNetWorthError, ValidationError
from backend.core.user_time import user_today
from backend.services import connector_fetch, connector_window, ledger, matching

logger = logging.getLogger(__name__)

MANUAL_BOOK = frozenset({"lunch_flow_personal"})
SURFACE = "connector_book"
_HELD_BANDS = frozenset({"strong", "review"})
_CHUNK_DAYS = 31
_MATCH_TYPES = frozenset({"cash", "credit"})


def _draft(row: dict) -> dict:
    amount = float(row["amount"])
    leg = "to" if amount > 0 else "from"
    return {
        "date": row["date"],
        "kind": "income" if amount > 0 else "expense",
        "category": None,
        "description": row.get("description") or "",
        "memo": row.get("memo") or "",
        "source": "feed",
        "cleared": True,  # posted at the bank — what the balance match below diffs against
        "external_refs": row["external_refs"],
        f"{leg}_account_id": row["linked_account_id"],
        f"{leg}_amount": abs(amount),
        f"{leg}_currency": row["currency"],
    }


def _book_chunk(
    provider_key: str, rows: list[dict], batch: Optional[dict], out: dict
) -> Optional[dict]:
    """Book one fetched window's rows into ``batch`` (created on first need); updates ``out``."""
    linked = [r for r in rows if r.get("linked_account_id")]
    out["unlinked"] += len(rows) - len(linked)
    drafts = [_draft(r) for r in linked]
    matches = matching.match_batch(drafts, context=matching.BatchContext(complete=False))
    to_book = [d for d, m in zip(drafts, matches) if m.band not in _HELD_BANDS]
    out["held_for_review"] += [
        {"date": d["date"], "description": d["description"], "existing_id": m.assigned.id}
        for d, m in zip(drafts, matches)
        if m.band in _HELD_BANDS and m.assigned is not None
    ]
    if not to_book:
        return batch
    if batch is None:
        batch = ledger.import_batches.create_batch(
            description=f"{provider_key} fetch and book ({user_today().isoformat()})",
            transaction_count=0,
            import_session_id=f"imp_{uuid.uuid4().hex[:12]}",
        )
    token = audit_context.set_audit_scope("user", SURFACE)
    try:
        created, skipped = ledger.bulk_create_transactions(
            to_book, batch_id=batch["id"], dedup_by_external_ref=True
        )
    finally:
        audit_context.clear_audit_scope(token)
    if created:
        try:
            from backend.services import match_review

            match_review.review_created_rows(created, batch_id=batch["id"])
        except Exception:  # noqa: BLE001 — the rows are booked; the review queue is extra
            logger.exception("connector_book: dedup review pass failed")
    out["booked"] += len(created)
    for t in created:
        acct = t.get("from_account_id") or t.get("to_account_id")
        if acct and (acct not in out["_oldest"] or t["date"] < out["_oldest"][acct]):
            out["_oldest"][acct] = t["date"]
    # A ref booked meanwhile, or one you deleted before (never re-added without you).
    out["skipped"] += len(skipped)
    return batch


def fetch_and_book(provider_key: str, since: Optional[str] = None) -> dict:
    """Walk ``[since, today]`` in ``_CHUNK_DAYS`` windows so a long history books in one run:
    each window is one provider fetch, well under ``connector_fetch``'s row cap."""
    if provider_key not in MANUAL_BOOK:
        raise ValidationError(f"{provider_key} has no manual fetch and book")
    provider = connector_fetch._resolve_provider(provider_key)
    since_r, before_r, _ = connector_window.default_window(provider, since, None)
    out: dict = {
        "status": "ok",
        "error": None,
        "window": {"since": since_r, "before": before_r},
        "booked": 0,
        "already_booked": 0,
        "pending_skipped": 0,
        "unlinked": 0,
        "skipped": 0,
        "held_for_review": [],
        "batch_id": None,
        "more_to_fetch": False,  # a window over the row cap: the next run books the rest
        "balances": [],
        "_oldest": {},  # account id -> oldest row this run booked into it
    }
    batch = None
    start, end = date.fromisoformat(since_r), date.fromisoformat(before_r)
    try:
        while start <= end:
            stop = min(end, start + timedelta(days=_CHUNK_DAYS - 1))
            fetched = connector_fetch.fetch(
                provider_key,
                since=start.isoformat(),
                before=stop.isoformat(),
                limit=connector_fetch._MAX_FETCH_ROWS,
                max_limit=connector_fetch._MAX_FETCH_ROWS,
            )
            if fetched["status"] != "ok":
                out |= {"status": fetched["status"], "error": fetched["error"]}
                break
            counts = fetched["counts"]
            out["already_booked"] += counts["already_booked"]
            out["pending_skipped"] += counts["pending_skipped"]
            out["more_to_fetch"] |= not fetched["window"]["complete"]
            batch = _book_chunk(provider_key, fetched["transactions"], batch, out)
            start = stop + timedelta(days=1)
        if out["status"] == "ok":
            out["balances"] = _align_and_match(provider_key, out["_oldest"])
    finally:
        out.pop("_oldest", None)
        if batch is not None:
            ledger.import_batches.set_status(
                batch["id"], "active" if out["booked"] else "rolled_back"
            )
            if out["booked"]:
                out["batch_id"] = batch["id"]
        if out["booked"] or out["balances"]:
            data_events.publish(["*"])
    # Undo rolls back the batch's rows only: a balance adjustment or a moved start would stay
    # behind and leave the balance wrong, so a run that made either is not offered for undo.
    out["undoable"] = bool(out["batch_id"]) and not any(
        n.get("adjusted_by") or n.get("start_moved_to") for n in out["balances"]
    )
    return out


def _align_and_match(provider_key: str, oldest: dict[str, str]) -> list[dict]:
    """Per linked account: move its start back to the oldest row this run booked (so past rows
    count, today's balance unchanged), then match its cleared balance to the bank's with one
    adjustment (owner decision 2026-11-13: auto-match, not a button). Cash and cards only —
    an investment account's value is its holdings. A card with a POSITIVE bank balance is
    left alone: whether Lunch Flow means owed or in-credit is unverified, and guessing wrong
    would flip the debt."""
    from backend.services import tracking_start

    notes = []
    for pa in connector_fetch.provider_accounts(provider_key).get("accounts") or []:
        account_id = pa.get("linked_account_id")
        acct = ledger.accounts.find_by_id(account_id) if account_id else None
        if acct is None:
            continue
        note: dict = {"account_id": account_id, "name": acct.get("name"), "bank_balance": None}
        notes.append(note)
        start = ledger.opening_date(acct, ledger.transactions.all())
        if oldest.get(account_id) and start and oldest[account_id] < start:
            try:
                tracking_start.align_tracking_start(account_id, oldest[account_id])
                note["start_moved_to"] = oldest[account_id]
            except OpenNetWorthError as exc:
                note["start_not_moved"] = exc.message or str(exc)
        balance = pa.get("balance")
        note["bank_balance"] = balance
        if acct.get("type") not in _MATCH_TYPES or balance is None:
            continue
        if (pa.get("currency") or "").upper() not in ("", (acct.get("currency") or "").upper()):
            note["not_matched"] = "the bank reports a different currency"
            continue
        if acct.get("type") == "credit" and balance > 0:
            note["not_matched"] = "a positive card balance may mean owed or in credit"
            continue
        token = audit_context.set_audit_scope("user", SURFACE)
        try:
            adj = ledger.reconcile(account_id, balance, against="cleared")
        finally:
            audit_context.clear_audit_scope(token)
        note["adjusted_by"] = _signed(adj, account_id) if adj else 0.0
    return notes


def _signed(adj: dict, account_id: str) -> float:
    if adj.get("to_account_id") == account_id:
        return float(adj.get("to_amount") or 0)
    return -float(adj.get("from_amount") or 0)
