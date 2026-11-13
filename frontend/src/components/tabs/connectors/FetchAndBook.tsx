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
  return parts.join(' ')
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
        setLastBatch((d as BookResult).batch_id)
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
        Books new posted transactions into linked accounts without Lucius. Anything that looks like
        a transaction you already have is left for you to check.
      </Text>
      {bookMsg && (
        <Text size="xs" tone={bookMsg.bad ? 'bad' : undefined} role="status">
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
