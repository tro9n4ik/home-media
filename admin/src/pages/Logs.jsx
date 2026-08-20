import { useState, useEffect, useRef } from 'react'
import { api } from '../lib/api'
import { Spinner, Section, showToast } from '../components/ui'
import { RefreshCw, Download } from 'lucide-react'

const STATUS_COLOR = {
  running:  'var(--green)',
  degraded: 'var(--amber)',
  failed:   'var(--red)',
  stopped:  'var(--ink-faint)',
  starting: 'var(--amber)',
}

export default function Logs() {
  const [logs,      setLogs]      = useState({})
  const [selected,  setSelected]  = useState(null)
  const [loading,   setLoading]   = useState(true)
  const [autoScroll,setAutoScroll]= useState(true)
  const [filter,    setFilter]    = useState('')
  const logRef = useRef()

  const load = async () => {
    try {
      const data = await api.allLogs(200)
      setLogs(data)
      if (!selected && Object.keys(data).length) {
        setSelected(Object.keys(data)[0])
      }
      setLoading(false)
    } catch(e) {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (autoScroll && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logs, selected, autoScroll])

  const currentLogs = selected && logs[selected]?.logs || []
  const filtered = filter
    ? currentLogs.filter(l => l.toLowerCase().includes(filter.toLowerCase()))
    : currentLogs

  const lineColor = (line) => {
    const l = line.toLowerCase()
    if (l.includes('error') || l.includes('critical') || l.includes('traceback')) return 'var(--red)'
    if (l.includes('warning') || l.includes('warn')) return 'var(--amber)'
    if (l.includes('started') || l.includes('running') || l.includes('health ok')) return 'var(--green)'
    return 'var(--ink-dim)'
  }

  const downloadLog = () => {
    if (!selected || !currentLogs.length) return
    const blob = new Blob([currentLogs.join('\n')], { type: 'text/plain' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${selected}-plugin.log`
    a.click()
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, animation: 'fadeIn .2s', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Section title={`Журналы · ${Object.keys(logs).length} модулей`} />
        <button onClick={load} className="btn sm">
          <RefreshCw size={13} /> Обновить
        </button>
      </div>

      <div style={{ display: 'flex', gap: 12, flex: 1, minHeight: 0 }}>

        {/* Список плагинов */}
        <div className="panel-card" style={{
          width: 180, flexShrink: 0, display: 'flex', flexDirection: 'column',
        }}>
          <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--line)', fontSize: 11, fontWeight: 600, color: 'var(--ink-faint)', textTransform: 'uppercase', letterSpacing: '.08em', fontFamily: 'var(--mono)' }}>
            Модули
          </div>
          <div style={{ flex: 1, overflow: 'auto', padding: 6, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {loading
              ? <div style={{ padding: 16, textAlign: 'center' }}><Spinner /></div>
              : Object.entries(logs).map(([id, data]) => (
                <button key={id} onClick={() => setSelected(id)} style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '8px 10px', borderRadius: 'var(--r)',
                  border: 'none', cursor: 'pointer', textAlign: 'left',
                  background: selected === id ? 'var(--panel-raised)' : 'transparent',
                  color: selected === id ? 'var(--ink)' : 'var(--ink-dim)',
                  fontFamily: 'var(--mono)', transition: '.12s',
                }}>
                  <span style={{
                    width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                    background: STATUS_COLOR[data.status] || 'var(--ink-faint)',
                    boxShadow: data.status === 'running' ? '0 0 6px var(--green)' : undefined,
                  }} />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 500 }}>{data.name}</div>
                    <div style={{ fontSize: 10, opacity: .6 }}>{data.logs.length} строк</div>
                  </div>
                </button>
              ))
            }
          </div>
        </div>

        {/* Лог */}
        <div className="panel-card" style={{
          flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column',
        }}>
          <div style={{
            padding: '8px 12px', borderBottom: '1px solid var(--line)',
            display: 'flex', gap: 8, alignItems: 'center',
          }}>
            <input
              placeholder="Фильтр..."
              value={filter}
              onChange={e => setFilter(e.target.value)}
              style={{ flex: 1, border: '1px solid var(--line)', borderRadius: 'var(--r)', padding: '5px 10px', outline: 'none' }}
            />
            <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--ink-dim)', cursor: 'pointer', whiteSpace: 'nowrap', fontFamily: 'var(--mono)' }}>
              <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)}
                style={{ accentColor: 'var(--amber)', width: 'auto' }} />
              прокрутка
            </label>
            <button onClick={downloadLog} title="Скачать лог" className="btn ghost sm">
              <Download size={12} /> Скачать
            </button>
            <span style={{ fontSize: 11, color: 'var(--ink-faint)', whiteSpace: 'nowrap', fontFamily: 'var(--mono)' }}>
              {filtered.length} строк
            </span>
          </div>

          <div ref={logRef} style={{
            flex: 1, overflow: 'auto', padding: '10px 14px',
            fontFamily: 'var(--mono)', fontSize: 12, lineHeight: 1.6,
          }}>
            {!selected
              ? <div style={{ color: 'var(--ink-faint)', padding: 20 }}>Выберите модуль</div>
              : filtered.length === 0
                ? <div style={{ color: 'var(--ink-faint)', padding: 20 }}>
                    {filter ? `Нет строк matching "${filter}"` : 'Лог пуст'}
                  </div>
                : filtered.map((line, i) => (
                  <div key={i} style={{ color: lineColor(line), whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                    {line}
                  </div>
                ))
            }
          </div>
        </div>

      </div>
    </div>
  )
}