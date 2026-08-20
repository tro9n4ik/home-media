import { NavLink, useLocation } from 'react-router-dom'
import { useState, useEffect } from 'react'
import {
  LayoutGrid, Tag, Search, Settings2,
  LogOut, Home, BookMarked, Plug, ScrollText
} from 'lucide-react'
import { usePluginPages } from '../../hooks/usePluginPages'
import { api } from '../../lib/api'

const ICON_MAP = {
  torrent:         () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>,
  prowlarr:        () => <Search size={16} />,
  home_assistant:  () => <Home size={16} />,
  watchlist:       () => <BookMarked size={16} />,
}

function PluginIcon({ pluginId }) {
  const Ic = ICON_MAP[pluginId]
  if (Ic) return <Ic />
  return <Plug size={16} />
}

const LED_COLOR = {
  running: 'var(--green)',
  starting: 'var(--amber)',
  degraded: 'var(--amber)',
  installing: 'var(--amber)',
  stopped: 'var(--ink-faint)',
  failed: 'var(--red)',
  error: 'var(--red)',
}

const MAIN_SLOTS = [
  { to: '/admin/',      label: 'Дашборд',  icon: LayoutGrid },
  { to: '/admin/plugins', label: 'Плагины', icon: Tag },
  { to: '/admin/logs',  label: 'Логи',     icon: ScrollText },
  { to: '/admin/settings', label: 'Опции',  icon: Settings2 },
]

export default function Sidebar() {
  const pluginPages = usePluginPages()
  const location = useLocation()
  const [theme] = useState(() => 'dark')

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', 'dark')
    localStorage.setItem('hm-theme', 'dark')
    window.postMessage({ type: 'hm:theme', theme: 'dark' }, '*')
  }, [])

  const logout = () => api.logout().finally(() => { window.location.href = '/admin/login' })

  const slotNum = (i) => String(i + 1).padStart(2, '0')

  return (
    <nav style={{
      background: 'var(--panel)', borderRight: '1px solid var(--line)',
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      padding: '20px 0', gap: 6, position: 'sticky', top: 0, height: '100vh',
    }}>
      <div className="rail-mark">HM·NAS</div>

      {MAIN_SLOTS.map((s, i) => {
        const isActive = s.to === '/admin/'
          ? location.pathname === '/admin/'
          : location.pathname.startsWith(s.to)
        const Icon = s.icon
        return (
          <NavLink key={s.to} to={s.to} className={`slot ${isActive ? 'active' : ''}`} title={s.label}>
            <span className="num">{slotNum(i)}</span>
            <Icon size={17} />
            <span className="led" />
          </NavLink>
        )
      })}

      {pluginPages.length > 0 && (
        pluginPages.map((page, i) => {
          const isActive = location.pathname.startsWith(page.path)
          return (
            <NavLink key={page.path} to={page.path} className={`slot ${isActive ? 'active' : ''}`} title={page.title || page.plugin_name}>
              <span className="num">{slotNum(i + MAIN_SLOTS.length)}</span>
              <PluginIcon pluginId={page.plugin_id} />
              <span className="led" style={{ background: LED_COLOR[page.status] || 'var(--ink-faint)', boxShadow: page.status === 'running' ? '0 0 6px var(--green)' : undefined }} />
            </NavLink>
          )
        })
      )}

      <div style={{ flex: 1 }} />
      <button
        onClick={logout}
        className="slot"
        title="Выйти"
        style={{ border: 'none', background: 'transparent' }}
      >
        <span className="num">XX</span>
        <LogOut size={17} />
        <span className="led" style={{ background: 'transparent' }} />
      </button>
    </nav>
  )
}