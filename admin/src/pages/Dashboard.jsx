import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Cpu, MemoryStick, HardDrive, Puzzle, ArrowRight } from 'lucide-react'
import { api } from '../lib/api'
import { Spinner, StatusDot, Btn, Section } from '../components/ui'

const STATUS_BLADE = {
  running: 'st-run', starting: 'st-deg', degraded: 'st-deg', installing: 'st-deg',
  installed: 'st-off', stopped: 'st-off', failed: 'st-err', error: 'st-err',
}
const STATUS_TEXT = {
  running: 'RUN', starting: 'START', degraded: 'DEGRADED', installing: 'INSTALL',
  installed: 'STOP', stopped: 'STOP', failed: 'ERR', error: 'ERR',
}
const STATUS_DOT = {
  running: 'var(--green)', starting: 'var(--amber)', degraded: 'var(--amber)', installing: 'var(--amber)',
  installed: 'var(--ink-faint)', stopped: 'var(--ink-faint)', failed: 'var(--red)', error: 'var(--red)',
}

function Gauge({ label, value, segments, color }) {
  const filled = Math.max(0, Math.min(segments, 10))
  return (
    <div className="gauge">
      <div className="l">{label}</div>
      <div className="v">{value}</div>
      <div className="bars">
        {Array.from({ length: 10 }, (_, i) => (
          <i key={i} className={i < filled ? 'on' : ''} style={i < filled && color ? { background: color } : undefined} />
        ))}
      </div>
    </div>
  )
}

const PATCH_COLORS = ['var(--green)', 'var(--amber)', 'var(--blue)', 'var(--yellow)']

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null)
  const [plugins, setPlugins] = useState([])
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

  if (loading) return <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}><Spinner /></div>

  const running = plugins.filter(p => p.status === 'running').length
  const START_PORT = 8100
  const END_PORT = 8200
  const TOTAL = END_PORT - START_PORT + 1
  const PORT_ROWS = 20

  // Карта занятых портов: порт → {plugin, color}
  const portMap = {}
  plugins.forEach((p, i) => {
    const port = p.assigned_port
    if (port) portMap[port] = { plugin: p, color: PATCH_COLORS[i % PATCH_COLORS.length] }
  })
  const busyCount = Object.keys(portMap).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 26 }}>
      {metrics && (
        <Section title="Показания системы">
          <div className="gauges">
            <Gauge label="CPU" value={`${metrics.cpu_percent}%`} segments={Math.round(metrics.cpu_percent / 10)} />
            <Gauge label={`RAM · ${metrics.ram_used_gb} / ${metrics.ram_total_gb} ГБ`} value={`${metrics.ram_percent}%`} segments={Math.round(metrics.ram_percent / 10)} />
            <Gauge label={`Диск · ${metrics.disk_used_gb} / ${metrics.disk_total_gb} ГБ`} value={`${metrics.disk_percent}%`} segments={Math.round(metrics.disk_percent / 10)} />
            <Gauge label="Модули" value={`${running} / ${plugins.length}`} segments={plugins.length ? Math.round(running / plugins.length * 10) : 0} />
          </div>
        </Section>
      )}

      <Section title={`Патч-панель · порты ${START_PORT}–${END_PORT}`} right={`${TOTAL - busyCount} своб. / ${TOTAL}`}>
        <div className="patch">
          <div className="patch-head">
            <span className="t">Пул портов плагинов</span>
            <span className="r">{Object.keys(portMap).length} занято</span>
          </div>
          {Array.from({ length: Math.ceil(TOTAL / PORT_ROWS) }, (_, r) => (
            <div className="patch-row" key={r}>
              <div className="rowlabel">{START_PORT + r * PORT_ROWS}</div>
              <div className="jacks">
                {Array.from({ length: PORT_ROWS }, (_, c) => {
                  const port = START_PORT + r * PORT_ROWS + c
                  if (port > END_PORT) return null
                  const owner = portMap[port]
                  return (
                    <div key={port} className={`jack ${owner ? 'busy' : ''}`} title={owner ? `${owner.plugin.name} · ${port}` : `${port} — свободно`}
                      style={owner ? { color: owner.color } : undefined}>
                      <span className="led" style={owner ? { background: owner.color } : undefined} />
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
          <div className="patch-legend">
            {plugins.map((p, i) => p.assigned_port && (
              <div className="pl-item" key={p.plugin_id}>
                <span className="pl-dot" style={{ background: PATCH_COLORS[i % PATCH_COLORS.length] }} />
                {p.name} · {p.assigned_port}
              </div>
            ))}
            <div className="pl-item"><span className="pl-dot" style={{ background: 'var(--panel-hi)', border: '1px solid var(--line)' }} />свободно</div>
          </div>
        </div>
      </Section>

      {plugins.length === 0 ? (
        <Section title="Установленные модули">
          <div className="panel-card" style={{ padding: '48px 32px', textAlign: 'center' }}>
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 18, opacity: .3 }}>
              <Puzzle size={52} strokeWidth={1} />
            </div>
            <div style={{ fontSize: 17, fontWeight: 700, fontFamily: 'var(--mono)', marginBottom: 8 }}>Модули не установлены</div>
            <div style={{ fontSize: 13, color: 'var(--ink-faint)', marginBottom: 22 }}>
              Установите .hm пакеты чтобы начать работу
            </div>
            <Btn variant="primary" onClick={() => nav('/admin/plugins')}>
              К модулям <ArrowRight size={14} />
            </Btn>
          </div>
        </Section>
      ) : (
        <Section title="Установленные модули" right={`${plugins.length} шт`}>
          <div className="blades">
            {plugins.map(p => (
              <div key={p.plugin_id} className={`blade ${STATUS_BLADE[p.status] || 'st-off'}`} style={p.enabled ? undefined : { opacity: .6 }}>
                <div className="blade-icon">
                  {p.ui_pages?.[0] && p.status === 'running'
                    ? <Cpu size={18} strokeWidth={1.5} style={{ cursor: 'pointer', color: 'var(--ink)' }} />
                    : <Puzzle size={18} strokeWidth={1.5} />}
                </div>
                <div className="blade-info" onClick={() => p.ui_pages?.[0] && nav(p.ui_pages[0].path)} style={{ cursor: p.ui_pages?.[0] ? 'pointer' : 'default' }}>
                  <div className="blade-name">
                    {p.name}
                    <span className="status-tag"><span className="d" />{STATUS_TEXT[p.status] || p.status}</span>
                  </div>
                  <div className="blade-desc">{p.description}</div>
                </div>
                <div className="blade-port">{p.assigned_port ? `:${p.assigned_port}` : '—'}</div>
                <StatusDot status={p.status} />
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  )
}