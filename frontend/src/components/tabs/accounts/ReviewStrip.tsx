/**
 * ReviewStrip.tsx — "N to review | Start review" in the register toolbar, beside the search it
 * filters: the count narrows the register to what needs review, Start review walks it card by card.
 */

import { WalletCards } from '../../../ui/icons'

export function ReviewStrip({
  count,
  onReview,
  onStartReview,
}: {
  count: number
  onReview: () => void
  onStartReview: () => void
}) {
  if (count <= 0) return null
  return (
    <div className="acct-pair" role="group" aria-label="Review">
      <button
        type="button"
        className="acct-pair-k acct-pair-btn"
        onClick={onReview}
        title="Show transactions that need review"
        aria-label={`${count} to review`}
      >
        <span className="acct-pair-dot" aria-hidden="true" />
        {count}
        <span className="acct-pair-lbl">to review</span>
      </button>
      <button
        type="button"
        className="acct-pair-act"
        onClick={onStartReview}
        title="Approve or skip each one in turn"
        aria-label="Start review"
      >
        <WalletCards size={13} aria-hidden="true" />
        <span className="acct-pair-lbl">Start review</span>
      </button>
    </div>
  )
}
