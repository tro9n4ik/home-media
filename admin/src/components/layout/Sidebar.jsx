import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import {
  LayoutGrid, Puzzle, Settings2, ScrollText, LogOut, Plus,
  Home, BookMarked, Search, Plug
} from 'lucide-react'
import { usePluginPages } from '../../hooks/usePluginPages'
import { api } from '../../lib/api'

const ICON_MAP = {
  torrent:         () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>,
  prowlarr:        () => <Search size={20} />,
  home_assistant:  () => <Home size={20} />,
  watchlist:       () => <BookMarked size={20} />,
}

function PluginIcon({ pluginId }) {
  const Ic = ICON_MAP[pluginId]
  if (Ic) return <Ic />
  return <Plug size={20} />
}

const LED_COLOR = {
  running: 'var(--success)',
  starting: 'var(--warning)',
  degraded: 'var(--warning)',
  installing: 'var(--warning)',
  stopped: 'var(--outline)',
  failed: 'var(--error)',
  error: 'var(--error)',
}

const MAIN_SLOTS = [
  { to: '/admin/',         label: 'Дашборд',  icon: LayoutGrid },
  { to: '/admin/plugins',  label: 'Плагины',  icon: Puzzle },
  { to: '/admin/logs',     label: 'Логи',     icon: ScrollText },
  { to: '/admin/settings', label: 'Опции',    icon: Settings2 },
]

export default function Sidebar() {
  const pluginPages = usePluginPages()
  const location = useLocation()
  const nav = useNavigate()

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', 'dark')
    localStorage.setItem('hm-theme', 'dark')
    window.postMessage({ type: 'hm:theme', theme: 'dark' }, '*')
  }, [])

  const logout = () => api.logout().finally(() => { window.location.href = '/admin/login' })

  return (
    <nav className="rail">
      <div className="rail-logo">HM</div>
      <button className="rail-fab" title="Установить плагин" onClick={() => nav('/admin/plugins')}>
        <Plus size={24} />
      </button>

      {MAIN_SLOTS.map(s => {
        const isActive = s.to === '/admin/'
          ? location.pathname === '/admin/'
          : location.pathname.startsWith(s.to)
        const Icon = s.icon
        return (
          <NavLink key={s.to} to={s.to} className={`rail-item ${isActive ? 'active' : ''}`} title={s.label}>
            <div className="indicator"><Icon size={20} /></div>
            <span className="label">{s.label}</span>
          </NavLink>
        )
      })}

      {pluginPages.map(page => {
        const isActive = location.pathname.startsWith(page.path)
        return (
          <NavLink key={page.path} to={page.path} className={`rail-item ${isActive ? 'active' : ''}`} title={page.title || page.plugin_name}>
            <div className="indicator">
              <PluginIcon pluginId={page.plugin_id} />
              <span className="dot" style={{ background: LED_COLOR[page.status] || 'var(--outline)' }} />
            </div>
            <span className="label" style={{ maxWidth: 64, overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {page.title || page.plugin_name}
            </span>
          </NavLink>
        )
      })}

      <div className="rail-spacer" />
      <button onClick={logout} className="rail-item" title="Выйти">
        <div className="indicator"><LogOut size={20} /></div>
        <span className="label">Выход</span>
      </button>
    </nav>
  )
}