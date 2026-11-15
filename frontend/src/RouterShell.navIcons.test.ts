import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const shell = readFileSync(resolve(__dirname, 'RouterShell.tsx'), 'utf8')
const assetIcons = readFileSync(resolve(__dirname, 'components/tabs/assets/icons.tsx'), 'utf8')

describe('sidebar icon contract', () => {
  it('uses the shared Lucide Box icon for Assets', () => {
    expect(shell).toMatch(/\bBox,/)
    expect(shell).toContain('assets: <Box {...ICON_PROPS} />')
    expect(shell).not.toContain("from './components/tabs/assets/icons'")
  })

  it('does not retain the bespoke sidebar Assets icon', () => {
    expect(assetIcons).not.toContain('NavAssetsIcon')
  })
})

const userMenu = readFileSync(resolve(__dirname, 'components/SidebarUserMenu.tsx'), 'utf8')

describe('sidebar account menu', () => {
  it('sits in the footer beside Search and opens the report dialog for feedback', () => {
    const footer = shell.slice(shell.indexOf('className="sidebar-util"'))
    expect(footer).toContain('<SidebarUserMenu')
    expect(footer).toMatch(/onFeedback=\{\(\) => openReportProblem\(\)\}/)
  })

  it('holds Hide amounts, Automations, Connectors, Settings and Send feedback — never Skills', () => {
    for (const label of [
      "'Hide amounts'",
      "'Automations'",
      "'Connectors'",
      "'Settings'",
      "'Send feedback'",
    ])
      expect(userMenu).toContain(label)
    expect(userMenu).not.toContain('Skills')
  })
})
