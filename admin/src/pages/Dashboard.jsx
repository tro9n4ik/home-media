import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Cpu, MemoryStick, HardDrive, Send, Download, Home, Puzzle, Upload, Loader2, MoreVertical } from 'lucide-react'
import { api } from '../lib/api'
import { Spinner, showToast } from '../components/ui'

const STATUS_CHIP = {
  running: 'ok', starting: 'warn', degraded: 'warn', installing: 'warn',
  installed: 'off', stopped: 'off', failed: 'err', error: 'err',
}
const STATUS_TEXT = {
  running: 'running', starting: 'starting', degraded: 'degraded', installing: 'installing',
  installed: 'stopped', stopped: 'stopped', failed: 'error', error: 'error',
}

const PLUGIN_ICON = {
  telegram_bot: Send,
  torrents: Download,
  home_assistant: Home,
}

const PATCH_COLORS = ['var(--primary)', 'var(--tertiary)', 'var(--secondary)', 'var(--warning)']

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null)
  const [plugins, setPlugins] = useState([])
  const [busy, setBusy] = useState({})
  const [loading, setLoading] = useState(true)
  const nav = useNavigate()

  useEffect(() => {
    const load = () =>
      Promise.all([api.metrics(), api.plugins()])
        .then(([m, p]) => { setMetrics(m); setPlugins(p) })
        .catch(() => {})
        .finally(() => setLoading(false))
    load()
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [])

  const toggle = async (p) => {
    const isActive = ['running', 'starting', 'degraded'].includes(p.status)
    if (!p.enabled && isActive) return
    setBusy(b => ({ ...b, [p.plugin_id]: true }))
    try {
      if (isActive) {
        await api.pluginStop(p.plugin_id)
        showToast(`${p.name} остановлен`)
      } else {
        await api.pluginStart(p.plugin_id)
        showToast(`${p.name} запускается...`)
      }
    } catch (e) { showToast(e.message, 'err') }
    setBusy(b => ({ ...b, [p.plugin_id]: false }))
    setTimeout(() => api.plugins().then(setPlugins).catch(() => {}), 900)
  }

  if (loading) return <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}><Spinner /></div>

  const running = plugins.filter(p => p.status === 'running').length
  const START_PORT = 8100
  const END_PORT = 8200
  const TOTAL = END_PORT - START_PORT + 1

  const portMap = {}
  plugins.forEach((p, i) => {
    if (p.assigned_port) portMap[p.assigned_port] = { plugin: p, color: PATCH_COLORS[i % PATCH_COLORS.length] }
  })
  const busyCount = Object.keys(portMap).length

  return (
    <div className="content" style={{ padding: 0 }}>
      {metrics && (
        <div>
          <div className="metrics">
            <div className="metric-card">
              <div className="metric-top">
                <span className="metric-label">CPU</span>
                <span className="metric-icon"><Cpu size={18} /></span>
              </div>
              <div className="metric-value">{metrics.cpu_percent}%</div>
              <div className="metric-track">
                <div className="metric-fill" style={{ width: `${Math.min(100, metrics.cpu_percent)}%`, background: 'var(--primary)' }} />
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-top">
                <span className="metric-label">RAM</span>
                <span className="metric-icon" style={{ background: 'var(--tertiary-container)', color: 'var(--on-tertiary-container)' }}><MemoryStick size={18} /></span>
              </div>
              <div className="metric-value">{metrics.ram_used_gb} / {metrics.ram_total_gb} ГБ</div>
              <div className="metric-track">
                <div className="metric-fill" style={{ width: `${Math.min(100, metrics.ram_percent)}%`, background: 'var(--tertiary)' }} />
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-top">
                <span className="metric-label">Диск</span>
                <span className="metric-icon" style={{ background: 'var(--secondary-container)', color: 'var(--on-secondary-container)' }}><HardDrive size={18} /></span>
              </div>
              <div className="metric-value">{metrics.disk_percent}%</div>
              <div className="metric-track">
                <div className="metric-fill" style={{ width: `${Math.min(100, metrics.disk_percent)}%`, background: 'var(--secondary)' }} />
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-top">
                <span className="metric-label">Плагины</span>
                <span className="metric-icon" style={{ background: 'var(--success-container)', color: 'var(--on-success-container)' }}><Puzzle size={18} /></span>
              </div>
              <div className="metric-value">{running} / {plugins.length} активны</div>
              <div className="metric-track">
                <div className="metric-fill" style={{ width: plugins.length ? `${Math.round(running / plugins.length * 100)}%` : 0, background: 'var(--success)' }} />
              </div>
            </div>
          </div>
        </div>
      )}

      <div>
        <div className="portmap-card">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>Карта портов</span>
            <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--on-surface-variant)' }}>{START_PORT}–{END_PORT} · {busyCount} занято</span>
          </div>
          <div className="portmap-grid">
            {Array.from({ length: TOTAL }, (_, i) => {
              const port = START_PORT + i
              const owner = portMap[port]
              return <div key={port} className={`pcell ${owner ? 'busy' : ''}`}
                title={owner ? `${owner.plugin.name} · ${port}` : `${port} — свободно`}
                style={owner ? { background: owner.color } : undefined} />
            })}
          </div>
          <div className="portmap-legend">
            {plugins.map((p, i) => p.assigned_port && (
              <div className="legend-item" key={p.plugin_id}>
                <span className="legend-dot" style={{ background: PATCH_COLORS[i % PATCH_COLORS.length] }} />
                {p.name} · {p.assigned_port}
              </div>
            ))}
            <div className="legend-item">
              <span className="legend-dot" style={{ background: 'var(--surface-container-high)' }} />
              свободно
            </div>
          </div>
        </div>
      </div>

      <div>
        <div className="section-head">
          <h2>Плагины</h2>
          <span className="count">{plugins.length} установлено</span>
        </div>
        {plugins.length === 0 ? (
          <div className="empty-state">
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16, opacity: .4 }}>
              <Puzzle size={52} strokeWidth={1} />
            </div>
            <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 4 }}>Плагины не установлены</div>
            <div className="hint">Установите .hm пакеты чтобы начать работу</div>
            <button className="fab-ext" onClick={() => nav('/admin/plugins')}>
              <Upload size={18} /> Установить плагин
            </button>
          </div>
        ) : (
          <div className="plugin-list" style={{ marginTop: 12 }}>
            {plugins.map(p => {
              const PIcon = PLUGIN_ICON[p.plugin_id] || Puzzle
              const isBusy = ['starting', 'installing'].includes(p.status)
              return (
                <div key={p.plugin_id} className="plugin-card" style={p.enabled ? undefined : { opacity: .65 }}>
                  <div className="plugin-avatar" onClick={() => p.ui_pages?.[0] && nav(p.ui_pages[0].path)}
                    style={{ cursor: p.ui_pages?.[0] ? 'pointer' : 'default' }}>
                    {isBusy
                      ? <Loader2 size={20} style={{ animation: 'spin .7s linear infinite' }} />
                      : <PIcon size={20} />}
                  </div>
                  <div className="plugin-info" onClick={() => p.ui_pages?.[0] && nav(p.ui_pages[0].path)}
                    style={{ cursor: p.ui_pages?.[0] ? 'pointer' : 'default' }}>
                    <div className="plugin-name">
                      {p.name}
                      <span className={`chip ${STATUS_CHIP[p.status] || 'off'}`}>
                        <span className="dot" />{STATUS_TEXT[p.status] || p.status}
                      </span>
                      {!p.enabled && <span className="chip off">no-autostart</span>}
                    </div>
                    <div className="plugin-desc">{p.description}</div>
                  </div>
                  <div className="plugin-port">{p.assigned_port ? `:${p.assigned_port}` : '—'}</div>
                  <button className={`switch ${['running', 'starting', 'degraded'].includes(p.status) ? 'on' : 'off'}`}
                    disabled={isBusy || busy[p.plugin_id]}
                    onClick={() => toggle(p)}
                    title={['running', 'starting', 'degraded'].includes(p.status) ? 'Остановить' : 'Запустить'} />
                  <button className="icon-btn" onClick={() => nav('/admin/plugins')} title="Управление">
                    <MoreVertical size={20} />
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {plugins.length > 0 && (
        <div className="fab-row">
          <button className="fab-ext" onClick={() => nav('/admin/plugins')}>
            <Upload size={18} /> Установить плагин
          </button>
        </div>
      )}
    </div>
  )
}