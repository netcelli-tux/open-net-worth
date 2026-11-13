// "Fetch and book now": books a connector's new transactions with no model in the loop
// (services/connector_book.py, ADR 2026-09-05 amendment). Rendered in the connector's "Next: bring
// in transactions" step, so it shows on the connector page once an account is linked.
import { useState } from 'react'
import { authFetch } from '../../../api/client'
import { emitDataChanged } from '../../../lucius/bus'
import { Button, DateField, FormField, Stack, Text } from '../../ui'

/** Connectors with a manual fetch and book — mirrors ``connector_book.MANUAL_BOOK``. */
export const MANUAL_BOOK = new Set(['lunch_flow_personal'])

interface BookResult {
  status: string
  error: string | null
  booked: number
  already_booked: number
  pending_skipped: number
  unlinked: number
  skipped: number
  held_for_review: { date: string; description: string }[]
  more_to_fetch: boolean
  batch_id: string | null
  undoable: boolean
  balances: {
    name: string
    bank_balance: number | null
    adjusted_by?: number
    start_moved_to?: string
    start_not_moved?: string
    not_matched?: string
  }[]
}

const money = (n: number) =>
  n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** One line per account whose balance or start date this run touched or couldn't. */
function balanceLines(r: BookResult): string[] {
  return r.balances.flatMap((b) => {
    const out: string[] = []
    if (b.start_moved_to)
      out.push(`${b.name}: start moved to ${b.start_moved_to} so past transactions count.`)
    if (b.start_not_moved) out.push(`${b.name}: start not moved — ${b.start_not_moved}`)
    if (b.adjusted_by)
      out.push(
        `${b.name}: adjusted by ${b.adjusted_by > 0 ? '+' : ''}${money(b.adjusted_by)} to match the bank's ${money(b.bank_balance ?? 0)}.`,
      )
    if (b.not_matched)
      out.push(`${b.name}: balance not matched — ${b.not_matched}. Set it by hand.`)
    return out
  })
}

/** One plain sentence for a fetch-and-book run — what landed and what was left alone. */
function bookSummary(r: BookResult): string {
  if (r.status !== 'ok') return `Fetch failed (${r.status})${r.error ? `: ${r.error}` : ''}.`
  const parts = [`Booked ${r.booked} new transaction${r.booked === 1 ? '' : 's'}.`]
  if (r.already_booked) parts.push(`${r.already_booked} already in your ledger.`)
  if (r.held_for_review.length)
    parts.push(
      `${r.held_for_review.length} look like transactions you already have and were not booked — check them in the ledger or ask Lucius.`,
    )
  if (r.unlinked) parts.push(`${r.unlinked} belong to accounts not linked below and were skipped.`)
  if (r.skipped) parts.push(`${r.skipped} skipped (deleted before, or booked meanwhile).`)
  if (r.pending_skipped) parts.push(`${r.pending_skipped} still pending.`)
  if (r.more_to_fetch) parts.push('There is more — run it again to book the rest.')
  if (r.batch_id && !r.undoable)
    parts.push('It also set balances or start dates, so it can’t be undone in one click.')
  return [parts.join(' '), ...balanceLines(r)].join('\n')
}

export function FetchAndBook({ provider }: { provider: string }) {
  const base = `/api/${provider.replace(/_/g, '-')}`
  const [since, setSince] = useState('')
  const [booking, setBooking] = useState(false)
  const [bookMsg, setBookMsg] = useState<{ text: string; bad: boolean } | null>(null)
  const [lastBatch, setLastBatch] = useState<string | null>(null)
  const [undoing, setUndoing] = useState(false)

  async function fetchAndBook() {
    setBooking(true)
    setBookMsg(null)
    setLastBatch(null)
    try {
      const r = await authFetch(`${base}/fetch-and-book`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(since ? { since } : {}),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setBookMsg({ text: d.detail || 'Could not fetch and book.', bad: true })
      } else {
        setBookMsg({ text: bookSummary(d as BookResult), bad: (d as BookResult).status !== 'ok' })
        setLastBatch((d as BookResult).undoable ? (d as BookResult).batch_id : null)
      }
      emitDataChanged(['*'])
    } catch {
      setBookMsg({ text: 'Could not reach the server.', bad: true })
    } finally {
      setBooking(false)
    }
  }

  async function undoRun() {
    if (!lastBatch) return
    setUndoing(true)
    try {
      const r = await authFetch(`/api/transactions/batches/${lastBatch}/rollback`, {
        method: 'POST',
      })
      const d = await r.json().catch(() => ({}))
      setBookMsg(
        r.ok
          ? { text: `Undone — removed ${d.deleted ?? 0} transaction(s).`, bad: false }
          : { text: d.detail || 'Could not undo this run.', bad: true },
      )
      if (r.ok) {
        setLastBatch(null)
        emitDataChanged(['*'])
      }
    } catch {
      setBookMsg({ text: 'Could not reach the server.', bad: true })
    } finally {
      setUndoing(false)
    }
  }

  return (
    <Stack gap="--space-2">
      <FormField
        label="Fetch from"
        htmlFor={`conn-${provider}-since`}
        help="Blank fetches the last two weeks. Pick an earlier date to import past transactions."
      >
        <DateField
          id={`conn-${provider}-since`}
          value={since}
          onChange={(e) => setSince(e.target.value)}
        />
      </FormField>
      <div>
        <Button size="sm" variant="secondary" loading={booking} onClick={fetchAndBook}>
          Fetch and book now
        </Button>
      </div>
      <Text size="xs" tone="faint">
        Books new posted transactions into linked accounts without Lucius, then sets each cash and
        card account to the bank&apos;s balance. Anything that looks like a transaction you already
        have is left for you to check.
      </Text>
      {bookMsg && (
        <Text
          size="xs"
          tone={bookMsg.bad ? 'bad' : undefined}
          role="status"
          style={{ whiteSpace: 'pre-line' }}
        >
          {bookMsg.text}
        </Text>
      )}
      {lastBatch && (
        <div>
          <Button size="sm" variant="ghost" loading={undoing} onClick={undoRun}>
            Undo this run
          </Button>
        </div>
      )}
    </Stack>
  )
}
