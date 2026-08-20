import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Upload, Play, Square, Trash2, ExternalLink, Puzzle, RefreshCw, Loader2, Power, AlertCircle, MoreVertical } from 'lucide-react'
import { api } from '../lib/api'
import { Btn, Spinner, Section, showToast } from '../components/ui'

const STATUS_CHIP = {
  running: 'ok', starting: 'warn', degraded: 'warn', installing: 'warn',
  installed: 'off', stopped: 'off', failed: 'err', error: 'err',
}
const STATUS_LABEL = {
  running: 'running', starting: 'starting', degraded: 'degraded', installing: 'installing',
  installed: 'stopped', stopped: 'stopped', failed: 'error', error: 'error',
}
const IS_BUSY = s => ['starting', 'installing'].includes(s)

export default function Plugins() {
  const [plugins,    setPlugins]    = useState([])
  const [loading,    setLoading]    = useState(true)
  const [installing, setInstalling] = useState(false)
  const [busy,       setBusy]       = useState({})
  const fileRef = useRef()
  const nav     = useNavigate()

  const load = () => {
    api.plugins()
      .then(p => { setPlugins(p); setLoading(false) })
      .catch(() => setLoading(false))
  }

  useEffect(() => {
    load()
    const id = setInterval(() => {
      setPlugins(prev => {
        if (prev.some(p => IS_BUSY(p.status))) load()
        return prev
      })
    }, 3000)
    return () => clearInterval(id)
  }, [])

  const install = async (file) => {
    if (!file) return
    setInstalling(true)
    showToast(`Устанавливаем ${file.name}...`, 'info', 8000)
    try {
      const p = await api.pluginInstall(file)
      showToast(`✓ ${p.name} v${p.version} установлен`)
      load()
    } catch (e) {
      showToast(e.message, 'err')
    }
    setInstalling(false)
    if (fileRef.current) fileRef.current.value = ''
  }

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
      setTimeout(load, 800)
    } catch (e) {
      showToast(e.message, 'err')
    }
    setBusy(b => ({ ...b, [p.plugin_id]: false }))
  }

  const toggleEnabled = async (p) => {
    setBusy(b => ({ ...b, [p.plugin_id]: true }))
    try {
      if (p.enabled) {
        await api.pluginDisable(p.plugin_id)
        showToast(`${p.name} отключён — автозапуск выключен`)
      } else {
        await api.pluginEnable(p.plugin_id)
        showToast(`${p.name} включён — будет запускаться при старте ядра`)
      }
      setTimeout(load, 800)
    } catch (e) {
      showToast(e.message, 'err')
    }
    setBusy(b => ({ ...b, [p.plugin_id]: false }))
  }

  const restart = async (p) => {
    setBusy(b => ({ ...b, [p.plugin_id]: true }))
    try {
      await api.pluginRestart(p.plugin_id)
      showToast(`${p.name} перезапускается...`)
      setTimeout(load, 800)
    } catch (e) {
      showToast(e.message, 'err')
    }
    setBusy(b => ({ ...b, [p.plugin_id]: false }))
  }

  const remove = async (p) => {
    if (!confirm(`Удалить ${p.name}?\nДанные плагина (токены, конфиг) будут удалены.`)) return
    try {
      await api.pluginDelete(p.plugin_id)
      showToast(`${p.name} удалён`)
      load()
    } catch (e) {
      showToast(e.message, 'err') }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, animation: 'fadeIn .2s' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, paddingBottom: 4 }}>
        <div className="section-head" style={{ marginBottom: 0 }}>
          <h2>Плагины</h2>
          <span className="count" style={{ marginLeft: 12 }}>{plugins.length} установлено</span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn sm" onClick={load} title="Обновить"><RefreshCw size={14} /></button>
          <label className="install-btn" style={{ cursor: installing ? 'not-allowed' : 'pointer' }}>
            {installing ? <Spinner size={16} /> : <Upload size={18} />}
            {installing ? 'Установка...' : 'Установить .hm пакет'}
            <input ref={fileRef} type="file" accept=".hm,.zip" style={{ display: 'none' }}
              disabled={installing} onChange={e => install(e.target.files[0])} />
          </label>
        </div>
      </div>

      {loading
        ? <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}><Spinner /></div>
        : plugins.length === 0
          ? (
            <div className="empty-state">
              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16, opacity: .4 }}>
                <Puzzle size={44} strokeWidth={1} />
              </div>
              <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 4 }}>Плагины не установлены</div>
              <div className="hint">Нажмите «Установить .hm пакет» чтобы добавить плагин</div>
            </div>
          )
          : (
            <div className="plugin-list">
              {plugins.map(p => {
                const disabled = busy[p.plugin_id] || IS_BUSY(p.status)
                return (
                  <div key={p.plugin_id} className="plugin-card" style={p.enabled ? undefined : { opacity: .65 }}>
                    <div className="plugin-avatar" onClick={() => p.ui_pages?.[0] && nav(p.ui_pages[0].path)}
                      style={{ cursor: p.ui_pages?.[0] ? 'pointer' : 'default' }}>
                      {IS_BUSY(p.status)
                        ? <Loader2 size={20} style={{ animation: 'spin .7s linear infinite' }} />
                        : <Puzzle size={20} strokeWidth={1.5} />}
                    </div>

                    <div className="plugin-info">
                      <div className="plugin-name">
                        <span onClick={() => p.ui_pages?.[0] && nav(p.ui_pages[0].path)}
                          style={{ cursor: p.ui_pages?.[0] ? 'pointer' : 'default' }}>
                          {p.name}
                        </span>
                        <span className={`chip ${STATUS_CHIP[p.status] || 'off'}`}>
                          <span className="dot" />{STATUS_LABEL[p.status] || p.status}
                        </span>
                        {!p.enabled && <span className="chip off"><Power size={11} /> no-autostart</span>}
                      </div>
                      <div className="plugin-desc" style={{ display: 'flex', gap: 14, alignItems: 'center', whiteSpace: 'nowrap' }}>
                        <span style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>v{p.version}</span>
                        {p.assigned_port && <span style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>:{p.assigned_port}</span>}
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.description}</span>
                      </div>
                      {p.last_error && (
                        <div className="errbox" style={{ marginTop: 8 }}>
                          <AlertCircle size={13} />
                          <span style={{ wordBreak: 'break-word' }}>{p.last_error}</span>
                        </div>
                      )}
                    </div>

                    <div style={{ display: 'flex', gap: 6, flexShrink: 0, alignItems: 'center' }}>
                      <button className={`switch ${p.enabled ? 'on' : 'off'}`}
                        title={p.enabled ? 'Автозапуск включён' : 'Автозапуск выключен'}
                        onClick={() => toggleEnabled(p)}
                        disabled={disabled} />
                      {p.ui_pages?.[0] && (
                        <button className="icon-btn" onClick={() => nav(p.ui_pages[0].path)} title="Открыть интерфейс">
                          <ExternalLink size={16} />
                        </button>
                      )}
                      {p.status === 'running' && (
                        <button className="icon-btn" onClick={() => restart(p)} disabled={busy[p.plugin_id]} title="Перезапустить">
                          <RefreshCw size={15} />
                        </button>
                      )}
                      <Btn size="sm"
                        variant={['running', 'starting', 'degraded'].includes(p.status) ? 'default' : 'success'}
                        onClick={() => toggle(p)}
                        disabled={disabled || !p.enabled}>
                        {busy[p.plugin_id]
                          ? <Loader2 size={12} style={{ animation: 'spin .7s linear infinite' }} />
                          : ['running', 'starting', 'degraded'].includes(p.status)
                            ? <><Square size={12} /> Стоп</>
                            : <><Play size={12} /> Старт</>}
                      </Btn>
                      <Btn size="sm" variant="danger" onClick={() => remove(p)}>
                        <Trash2 size={14} />
                      </Btn>
                      <button className="icon-btn" title="Ещё">
                        <MoreVertical size={18} />
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )
      }
    </div>
  )
}