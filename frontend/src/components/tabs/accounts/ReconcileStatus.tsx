/**
 * ReconcileStatus.tsx — "Reconciled … | Reconcile" in the register toolbar on an account page,
 * the same joined control as the review queue (ReviewStrip). A narrow toolbar keeps only the
 * status icon, which opens the reconcile popover itself.
 */

import { CircleCheck, ClockAlert } from '../../../ui/icons'
import { fDate } from '../../../utils/format'
import { ReconcilePopover } from './AccountHeader'
import { daysSinceReconcile, isReconcileOverdue } from './reconcileCadence'
import type { Account } from './types'

export function ReconcileStatus({
  account,
  onReconcile,
}: {
  account: Account
  onReconcile: (account: Account, realBalance: number) => void
}) {
  const last = account.lastReconciled
  const overdue = !!last && isReconcileOverdue(last)
  const icon =
    last && !overdue ? (
      <CircleCheck size={14} className="ok" aria-hidden="true" />
    ) : (
      <ClockAlert size={14} className="warn" aria-hidden="true" />
    )
  const text = !last ? (
    'Never reconciled'
  ) : overdue ? (
    <>
      Reconciled {fDate(last, 'numeric', 'auto')}{' '}
      <span className="warn">({daysSinceReconcile(last)} days ago)</span>
    </>
  ) : (
    `Reconciled ${fDate(last, 'numeric', 'auto')}`
  )
  return (
    <div className="acct-pair acct-pair--reconcile" role="group" aria-label="Reconciliation">
      <span
        className="acct-pair-k acct-pair-lbl"
        title={
          overdue ? 'Reconcile at least once a month, so a gap is still easy to trace.' : undefined
        }
      >
        {icon}
        {text}
      </span>
      <ReconcilePopover
        account={account}
        onReconcile={onReconcile}
        trigger={
          <>
            <span className="acct-pair-icon">{icon}</span>
            <span className="acct-pair-lbl">Reconcile</span>
          </>
        }
      />
    </div>
  )
}
