import Sidebar from './Sidebar'
import { useLocation } from 'react-router-dom'

const TITLES = {
  '/admin/':         ['Home.Media — панель управления', 'MODEL HM3-SYN · SERIAL DS920-LOCAL'],
  '/admin/plugins':  ['Home.Media — модули',            'ПАКЕТЫ .HM · INSTALL / START / STOP'],
  '/admin/logs':     ['Home.Media — журналы',           'REAL-TIME · 200 СТРОК'],
  '/admin/settings': ['Home.Media — настройки',         'СИСТЕМА · УЧЁТНАЯ ЗАПИСЬ · BACKUP'],
}

export default function Layout({ children }) {
  const location = useLocation()
  let h1 = 'Home.Media — панель управления'
  let tag = 'MODEL HM3-SYN · SERIAL DS920-LOCAL'
  for (const [prefix, t] of Object.entries(TITLES)) {
    if (location.pathname.startsWith(prefix)) { h1 = t[0]; tag = t[1]; break }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'var(--rail-w) 1fr', minHeight: '100vh' }}>
      <Sidebar />
      <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {/* Шильдик-шапка */}
        <div style={{
          background: 'var(--panel)', borderBottom: '1px solid var(--line)',
          padding: '14px 28px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, minWidth: 0 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 8, background: 'var(--panel-raised)', border: '1px solid var(--line)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontFamily: 'var(--mono)', fontWeight: 700, fontSize: 13, color: 'var(--amber)', flexShrink: 0,
            }}>HM</div>
            <div style={{ minWidth: 0 }}>
              <h1 style={{
                fontFamily: 'var(--mono)', fontWeight: 600, fontSize: 15,
                letterSpacing: '.06em', margin: 0, textTransform: 'uppercase',
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }}>{h1}</h1>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-faint)', marginTop: 3, letterSpacing: '.03em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{tag}</div>
            </div>
          </div>
        </div>

        <main style={{
          flex: 1, padding: '28px', overflowY: 'auto',
          animation: 'fadeUp .3s',
        }}>
          {children}
        </main>
      </div>
    </div>
  )
}