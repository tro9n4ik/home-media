import Sidebar from './Sidebar'
import { useLocation } from 'react-router-dom'

const TITLES = {
  '/admin/':         ['Дашборд',            'Home.Media v4.0.0 · панель управления'],
  '/admin/plugins':  ['Плагины',            'Установка · запуск · остановка модулей'],
  '/admin/logs':     ['Журналы',            'Логи ядра и плагинов в реальном времени'],
  '/admin/settings': ['Настройки',          'Система · учётная запись · резервное копирование'],
}

export default function Layout({ children }) {
  const location = useLocation()
  let h1 = 'Дашборд'
  let sub = 'Home.Media v4.0.0 · панель управления'
  for (const [prefix, t] of Object.entries(TITLES)) {
    if (location.pathname.startsWith(prefix)) { h1 = t[0]; sub = t[1]; break }
  }

  return (
    <div className="app">
      <Sidebar />
      <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <div className="topbar">
          <div>
            <h1>{h1}</h1>
            <div className="sub">{sub}</div>
          </div>
          <div className="topbar-actions">
            <div className="avatar">HM</div>
          </div>
        </div>

        <main className="content" style={{ flex: 1, overflowY: 'auto', animation: 'fadeUp .3s' }}>
          {children}
        </main>
      </div>
    </div>
  )
}