import { useCallback, useEffect, useState } from 'react'
import { authFetch } from '../../../api/client'
import { Button, DateField, FormField, PasswordField, Stack, Text, useSecretReveal } from '../../ui'
import { unrevealed, useConnectorSave, useTouched } from './formSave'
import { revealConnectorSecret } from './secrets'
import { ConnectorStatusLine } from './ConnectorStatusLine'
import { ConnectorAccountsList } from './ConnectorAccountsList'

// Lunch Flow Personal API connector over /api/lunch-flow-personal/* — LunchFlowPersonalSection's
// shape with an API key instead of an access token. The key is typed by the operator, so it
// is revealable through the shared eye; a blank field on save keeps the saved one.

interface LunchFlowPersonalStatus {
  configured: boolean
  enabled: boolean
  has_api_key: boolean
  last_synced_at: string | null
  last_status: string
  last_error: string | null
}

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

interface LunchFlowPersonalForm {
  api_key: string
}

/** The seed for `load()` AND the baseline the footer's Save compares against. `enabled`
 *  is gone from this form (the top-level Pause/Resume button owns it now), which leaves
 *  `api_key` — and that never round-trips (write-only) — so the form has no server
 *  value left to seed itself from; it is always this same blank shape. */
function lunchFlowPersonalFormOf(): LunchFlowPersonalForm {
  return {
    api_key: '',
  }
}

export function LunchFlowPersonalSection() {
  const [cfg, setCfg] = useState<LunchFlowPersonalStatus | null>(null)
  const [form, setForm] = useState<LunchFlowPersonalForm | null>(null)
  const [error, setError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState<string | null>(null)
  const [since, setSince] = useState('')
  const [booking, setBooking] = useState(false)
  const [bookMsg, setBookMsg] = useState<{ text: string; bad: boolean } | null>(null)
  const [lastBatch, setLastBatch] = useState<string | null>(null)
  const [undoing, setUndoing] = useState(false)

  function load() {
    setError(false)
    authFetch('/api/lunch-flow-personal/status')
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((c: LunchFlowPersonalStatus) => {
        setCfg(c)
        setForm(lunchFlowPersonalFormOf())
      })
      .catch(() => setError(true))
  }

  useEffect(load, [])

  async function save(): Promise<boolean> {
    if (!form || !cfg) return false
    setSaving(true)
    setSaveErr(null)
    try {
      const body: Record<string, unknown> = { enabled: cfg.configured ? cfg.enabled : true }
      if (form.api_key.trim()) body.api_key = form.api_key.trim()
      const r = await authFetch('/api/lunch-flow-personal/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        setSaveErr(d.detail || 'Could not save the API key.')
        return false
      }
      setForm((f) => f && { ...f, api_key: '' })
      load()
      return true
    } catch {
      setSaveErr('Could not save — could not reach the server.')
      return false
    } finally {
      setSaving(false)
    }
  }

  async function fetchAndBook() {
    setBooking(true)
    setBookMsg(null)
    setLastBatch(null)
    try {
      const r = await authFetch('/api/lunch-flow-personal/fetch-and-book', {
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
      load()
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
      if (r.ok) setLastBatch(null)
    } catch {
      setBookMsg({ text: 'Could not reach the server.', bad: true })
    } finally {
      setUndoing(false)
    }
  }

  const setToken = useCallback((v: string) => setForm((f) => f && { ...f, api_key: v }), [])
  const token = useSecretReveal({
    saved: !!cfg?.has_api_key,
    value: form?.api_key ?? '',
    onChange: setToken,
    reveal: useCallback(() => revealConnectorSecret('lunch_flow_personal', 'api_key'), []),
  })

  const tokenValid = !form || !!form.api_key.trim() || !!cfg?.has_api_key
  const tokenTouched = useTouched()

  useConnectorSave({
    ready: !!form && !!cfg && tokenValid,
    values: form && { ...form, api_key: unrevealed(form.api_key, token) },
    baseline: cfg ? lunchFlowPersonalFormOf() : form,
    saving,
    error: saveErr,
    save,
  })

  if (error) {
    return (
      <Text size="sm" tone="bad">
        Could not load the Lunch Flow Personal connector status.
      </Text>
    )
  }
  if (!cfg || !form) {
    return (
      <Text size="sm" tone="faint">
        Loading…
      </Text>
    )
  }

  const set = <K extends keyof LunchFlowPersonalForm>(k: K, v: LunchFlowPersonalForm[K]) =>
    setForm((f) => f && { ...f, [k]: v })

  return (
    <Stack gap="--space-4">
      <Text size="sm" tone="faint">
        In{' '}
        <a href="https://www.lunchflow.app" target="_blank" rel="noreferrer">
          Lunch Flow
        </a>
        , create an API destination and paste its API key here. Fetching and booking transactions is
        Lucius's job — automate it with a template below.
      </Text>

      {cfg.configured && !cfg.enabled && (
        <Text size="xs" tone="warn">
          Currently paused — saving here won&apos;t resume it. Use Resume on the connector card to
          turn it back on.
        </Text>
      )}

      <ConnectorStatusLine lastSyncedAt={cfg.last_synced_at} lastStatus={cfg.last_status} />
      {cfg.last_error && (
        <Text size="xs" tone="bad">
          Last error: {cfg.last_error}
        </Text>
      )}

      <FormField
        label="API key"
        htmlFor="conn-lfp-key"
        required
        help={token.caption || 'The API key of a Lunch Flow API destination.'}
        error={
          token.error ||
          (tokenTouched.touched && !tokenValid ? 'An API key is required.' : undefined)
        }
      >
        <PasswordField
          id="conn-lfp-key"
          value={form.api_key}
          placeholder={cfg.has_api_key ? '••••••••' : 'Paste your API key'}
          onChange={(e) => set('api_key', e.target.value)}
          onBlur={tokenTouched.onBlur}
          {...token.fieldProps}
        />
      </FormField>

      {saveErr && (
        <Text size="xs" tone="bad">
          {saveErr}
        </Text>
      )}

      {cfg.configured && (
        <Stack gap="--space-2">
          <FormField
            label="Fetch from"
            htmlFor="conn-lfp-since"
            help="Blank fetches the last two weeks. Pick an earlier date to import past transactions."
          >
            <DateField
              id="conn-lfp-since"
              value={since}
              onChange={(e) => setSince(e.target.value)}
            />
          </FormField>
          <div>
            <Button
              size="sm"
              variant="secondary"
              loading={booking}
              disabled={!cfg.enabled}
              onClick={fetchAndBook}
            >
              Fetch and book now
            </Button>
          </div>
          <Text size="xs" tone="faint">
            Books new posted transactions into linked accounts without Lucius. Anything that looks
            like a transaction you already have is left for you to check.
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
      )}

      <ConnectorAccountsList provider="lunch_flow_personal" providerLabel="Lunch Flow" />
    </Stack>
  )
}
