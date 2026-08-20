import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Upload, Play, Square, Trash2, ExternalLink, Puzzle, RefreshCw, Loader2, Power, AlertCircle } from 'lucide-react'
import { api } from '../lib/api'
import { Btn, Spinner, Empty, Section, showToast } from '../components/ui'

const STATUS_BLADE = {
  running: 'st-run', starting: 'st-deg', degraded: 'st-deg', installing: 'st-deg',
  installed: 'st-off', stopped: 'st-off', failed: 'st-err', error: 'st-err',
}
const STATUS_LABEL = {
  running: 'RUN', starting: 'START', degraded: 'DEGRADED', installing: 'INSTALL',
  installed: 'STOP', stopped: 'STOP', failed: 'ERR', error: 'ERR',
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <Section title={`Установленные модули · ${plugins.length} шт`} />
        <div style={{ display: 'flex', gap: 8 }}>
          <Btn size="sm" variant="ghost" onClick={load}><RefreshCw size={13} /></Btn>
          <label className="install-btn" style={{ cursor: installing ? 'not-allowed' : 'pointer' }}>
            {installing ? <Spinner size={14} /> : <Upload size={14} />}
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
            <div className="panel-card">
              <Empty icon={<Puzzle size={44} strokeWidth={1} />} text="Нет установленных плагинов" />
              <div style={{ textAlign: 'center', paddingBottom: 28, color: 'var(--ink-faint)', fontSize: 13, fontFamily: 'var(--mono)' }}>
                Нажмите «Установить .hm пакет» чтобы добавить плагин
              </div>
            </div>
          )
          : (
            <div className="blades">
              {plugins.map(p => (
                <div key={p.plugin_id} className={`blade ${STATUS_BLADE[p.status] || 'st-off'}`} style={p.enabled ? undefined : { opacity: .65 }}>

                  {/* Иконка */}
                  <div className="blade-icon" onClick={() => p.ui_pages?.[0] && nav(p.ui_pages[0].path)}
                    style={{ cursor: p.ui_pages?.[0] ? 'pointer' : 'default' }}>
                    {IS_BUSY(p.status)
                      ? <Loader2 size={18} style={{ animation: 'spin .7s linear infinite', color: 'var(--amber)' }} />
                      : <Puzzle size={18} strokeWidth={1.5} />}
                  </div>

                  {/* Info */}
                  <div className="blade-info">
                    <div className="blade-name">
                      <span style={{ cursor: p.ui_pages?.[0] ? 'pointer' : 'default', color: p.ui_pages?.[0] ? 'var(--ink)' : 'var(--ink)' }}
                        onClick={() => p.ui_pages?.[0] && nav(p.ui_pages[0].path)}>
                        {p.name}
                      </span>
                      <span className="status-tag"><span className="d" />{STATUS_LABEL[p.status] || p.status}</span>
                      {!p.enabled && <span className="status-tag st-off"><Power size={9} /> no-autostart</span>}
                    </div>
                    <div className="blade-desc" style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
                      <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-faint)' }}>v{p.version}</span>
                      {p.assigned_port && (
                        <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-faint)' }}>:{p.assigned_port}</span>
                      )}
                      <span>{p.description}</span>
                    </div>
                    {p.last_error && (
                      <div className="errbox" style={{ marginTop: 8 }}>
                        <AlertCircle size={13} />
                        <span style={{ wordBreak: 'break-word' }}>{p.last_error}</span>
                      </div>
                    )}
                  </div>

                  {/* Actions */}
                  <div style={{ display: 'flex', gap: 6, flexShrink: 0, alignItems: 'center' }}>
                    <button
                      className="blade-toggle on"
                      title={p.enabled ? 'Автозапуск включён' : 'Автозапуск выключен'}
                      onClick={() => toggleEnabled(p)}
                      disabled={busy[p.plugin_id] || IS_BUSY(p.status)}
                    />
                    {p.ui_pages?.[0] && (
                      <button className="icon-btn" onClick={() => nav(p.ui_pages[0].path)} title="Открыть интерфейс">
                        <ExternalLink size={14} />
                      </button>
                    )}
                    {p.status === 'running' && (
                      <button className="icon-btn" onClick={() => restart(p)} disabled={busy[p.plugin_id]} title="Перезапустить">
                        <RefreshCw size={13} />
                      </button>
                    )}
                    <Btn size="sm"
                      variant={['running', 'starting', 'degraded'].includes(p.status) ? 'default' : 'success'}
                      onClick={() => toggle(p)}
                      disabled={busy[p.plugin_id] || IS_BUSY(p.status) || !p.enabled}>
                      {busy[p.plugin_id]
                        ? <Loader2 size={12} style={{ animation: 'spin .7s linear infinite' }} />
                        : ['running', 'starting', 'degraded'].includes(p.status)
                          ? <><Square size={12} /> Стоп</>
                          : <><Play size={12} /> Старт</>}
                    </Btn>
                    <Btn size="sm" variant="danger" onClick={() => remove(p)}>
                      <Trash2 size={13} />
                    </Btn>
                  </div>
                </div>
              ))}
            </div>
          )
      }
    </div>
  )
}