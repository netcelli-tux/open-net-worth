import { ActionMenu } from './ui/ActionMenu'
import {
  Bug,
  ChevronsUpDown,
  Eye,
  EyeOff,
  Settings as SettingsIcon,
  Share2,
  User,
  Workflow,
} from '../ui/icons'
import type { TabId } from '../tabs'

const ICON = { size: 16, strokeWidth: 1.6, 'aria-hidden': true } as const

// The destinations this menu holds, so the trigger can read as "you are in here".
const MENU_TABS = new Set<TabId>(['automations', 'connectors', 'settings', 'profile'])

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  return parts
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join('')
}

/** The sidebar's footer: who you are, and the app-wide controls that are not places you work
 *  (privacy, setup surfaces, feedback). One row instead of five keeps the rail for your money. */
export function SidebarUserMenu({
  name,
  activeTab,
  amountsHidden,
  onTogglePrivacy,
  onGo,
  onFeedback,
  connectorsAttention,
  connectorsSignInOnly,
}: {
  name: string | null | undefined
  activeTab: TabId
  amountsHidden: boolean
  onTogglePrivacy: () => void
  onGo: (tab: TabId) => void
  onFeedback: () => void
  connectorsAttention: number
  connectorsSignInOnly: boolean
}) {
  const display = name?.trim() || 'You'
  const mono = name?.trim() ? initials(name) : ''
  const dot =
    connectorsAttention > 0 ? (
      <span
        className={`sidebar-attention-dot${connectorsSignInOnly ? ' sidebar-attention-dot-warn' : ''}`}
        role="img"
        aria-label="A connector needs attention"
      />
    ) : null

  return (
    <ActionMenu
      label="Account menu"
      title={display}
      className="sidebar-user-wrap"
      triggerClassName={`sidebar-item sidebar-user${MENU_TABS.has(activeTab) ? ' active' : ''}`}
      placement="above"
      align="start"
      trigger={
        <>
          <span className="sidebar-icon" style={{ position: 'relative' }}>
            <span className="sidebar-avatar" aria-hidden="true">
              {mono || <User size={13} strokeWidth={1.8} />}
            </span>
            {dot}
          </span>
          <span className="sidebar-label sidebar-user-name">{display}</span>
          <ChevronsUpDown className="sidebar-user-chev" {...ICON} />
        </>
      }
      items={[
        {
          label: amountsHidden ? 'Show amounts' : 'Hide amounts',
          icon: amountsHidden ? <EyeOff {...ICON} /> : <Eye {...ICON} />,
          hint: 'H',
          onSelect: onTogglePrivacy,
        },
        {
          label: 'Automations',
          icon: <Workflow {...ICON} />,
          separatorBefore: true,
          onSelect: () => onGo('automations'),
        },
        {
          label: 'Connectors',
          icon: (
            <span className="kebab-item-icon">
              <Share2 {...ICON} />
              {dot}
            </span>
          ),
          onSelect: () => onGo('connectors'),
        },
        {
          label: 'Settings',
          icon: <SettingsIcon {...ICON} />,
          onSelect: () => onGo('settings'),
        },
        {
          label: 'Send feedback',
          icon: <Bug {...ICON} />,
          separatorBefore: true,
          onSelect: onFeedback,
        },
      ]}
    />
  )
}
