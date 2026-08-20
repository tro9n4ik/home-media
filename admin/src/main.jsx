import React, { useState, useEffect } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import './index.css'

import Layout    from './components/layout/Layout'
import Login     from './pages/Login'
import Setup     from './pages/Setup'
import Dashboard from './pages/Dashboard'
import Plugins   from './pages/Plugins'
import PluginPage from './pages/PluginPage'
import Settings  from './pages/Settings'
import Logs      from './pages/Logs'
import { api }   from './lib/api'
import { Spinner } from './components/ui'

function AuthGuard({ children }) {
  const [state, setState] = useState('loading')

  useEffect(() => {
    api.setupNeeded()
      .then(({ needed }) => {
        if (needed) { setState('setup'); return }
        return api.me().then(() => setState('ok')).catch(() => setState('login'))
      })
      .catch(() => setState('login'))
  }, [])

  if (state === 'loading') return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
      <Spinner size={32} />
    </div>
  )
  if (state === 'setup') return <Navigate to="/admin/setup" replace />
  if (state === 'login') return <Navigate to="/admin/login" replace />
  return children
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/admin/login" element={<Login />} />
        <Route path="/admin/setup" element={<Setup />} />

        <Route path="/admin/*" element={
          <AuthGuard>
            <Layout>
              <Routes>
                <Route path="/"                    element={<Dashboard />} />
                <Route path="/plugins"             element={<Plugins />} />
                <Route path="/plugins/:pluginId/*" element={<PluginPage />} />
                <Route path="/settings"            element={<Settings />} />
                <Route path="/logs"                element={<Logs />} />
                <Route path="*"                    element={<Navigate to="/admin/" replace />} />
              </Routes>
            </Layout>
          </AuthGuard>
        } />

        <Route path="*" element={<Navigate to="/admin/" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
)
