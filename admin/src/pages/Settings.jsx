import { useState, useRef, useEffect } from 'react'
import { api } from '../lib/api'
import { Card, Btn, Spinner, Section, showToast } from '../components/ui'
import { Download, Upload, CheckCircle, AlertCircle, Key, Info } from 'lucide-react'

const VERSION = '4.0.0'

const inputStyle = {
  width: '100%', padding: '8px 12px', borderRadius: 'var(--r)',
  border: '1px solid var(--line)', background: 'var(--panel)',
  color: 'var(--ink)', fontSize: 12, fontFamily: 'var(--mono)', outline: 'none',
}

function PanelHead({ icon, children }) {
  return (
    <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--line)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--mono)', fontSize: 13 }}>
      {icon} {children}
    </div>
  )
}

export default function Settings() {
  const [user,         setUser]         = useState(null)
  const [curPass,      setCurPass]      = useState('')
  const [newPass,      setNewPass]      = useState('')
  const [newPass2,     setNewPass2]     = useState('')
  const [passLoading,  setPassLoading]  = useState(false)
  const [importing,    setImporting]    = useState(false)
  const [exporting,    setExporting]    = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [sysInfo,      setSysInfo]      = useState(null)
  const fileRef = useRef()

  useEffect(() => {
    api.me().then(setUser).catch(() => {})
    api.metrics().then(setSysInfo).catch(() => {})
  }, [])

  const changePassword = async (e) => {
    e.preventDefault()
    if (newPass.length < 8)   { showToast('Пароль минимум 8 символов', 'err'); return }
    if (newPass !== newPass2)  { showToast('Пароли не совпадают', 'err'); return }
    setPassLoading(true)
    try {
      await api.changePassword({ current_password: curPass, new_password: newPass })
      showToast('✓ Пароль изменён')
      setCurPass(''); setNewPass(''); setNewPass2('')
    } catch(e) {
      showToast(e.message, 'err')
    }
    setPassLoading(false)
  }

  const exportSettings = async () => {
    setExporting(true)
    try {
      const blob = await api.exportSettings()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `home-media-settings-${new Date().toISOString().slice(0,10)}.json`
      a.click()
      URL.revokeObjectURL(url)
      showToast('✓ Настройки экспортированы')
    } catch(e) { showToast(e.message, 'err') }
    setExporting(false)
  }

  const importSettings = async (file) => {
    if (!file) return
    setImporting(true); setImportResult(null)
    try {
      const result = await api.importSettings(file)
      setImportResult(result)
      showToast(result.message)
    } catch(e) {
      showToast(e.message, 'err')
      setImportResult({ status: 'error', message: e.message })
    }
    setImporting(false)
    if (fileRef.current) fileRef.current.value = ''
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, animation: 'fadeIn .2s', maxWidth: 600 }}>
      {/* О системе */}
      <Section title="О системе">
        <Card>
          <PanelHead><Info size={15} /> Система</PanelHead>
          <div style={{ padding: 16, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {[
              ['Версия',      `Home.Media v${VERSION}`],
              ['Пользователь', user?.username || '—'],
              ['CPU',         sysInfo ? `${sysInfo.cpu_percent}%` : '—'],
              ['RAM',         sysInfo ? `${sysInfo.ram_used_gb} / ${sysInfo.ram_total_gb} GB (${sysInfo.ram_percent}%)` : '—'],
              ['Диск',        sysInfo ? `${sysInfo.disk_used_gb} / ${sysInfo.disk_total_gb} GB (${sysInfo.disk_percent}%)` : '—'],
            ].map(([label, value]) => (
              <div key={label} style={{ background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 'var(--r)', padding: '10px 14px' }}>
                <div style={{ fontSize: 10, color: 'var(--ink-faint)', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 3, fontFamily: 'var(--mono)' }}>{label}</div>
                <div style={{ fontSize: 14, fontWeight: 600, fontFamily: 'var(--mono)' }}>{value}</div>
              </div>
            ))}
          </div>
        </Card>
      </Section>

      {/* Смена пароля */}
      <Section title="Смена пароля">
        <Card>
          <PanelHead><Key size={15} /> Учётная запись</PanelHead>
          <form onSubmit={changePassword} style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div>
              <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 5, fontFamily: 'var(--mono)' }}>Текущий пароль</div>
              <input style={inputStyle} type="password" value={curPass}
                onChange={e => setCurPass(e.target.value)} placeholder="••••••••" required />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div>
                <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 5, fontFamily: 'var(--mono)' }}>Новый пароль</div>
                <input style={inputStyle} type="password" value={newPass}
                  onChange={e => setNewPass(e.target.value)} placeholder="мин. 8 символов" required />
              </div>
              <div>
                <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 5, fontFamily: 'var(--mono)' }}>Повторите пароль</div>
                <input style={inputStyle} type="password" value={newPass2}
                  onChange={e => setNewPass2(e.target.value)} placeholder="повторите" required />
              </div>
            </div>
            <div>
              <Btn variant="primary" disabled={passLoading || !curPass || !newPass || !newPass2}>
                {passLoading ? <Spinner size={14} /> : <Key size={14} />}
                {passLoading ? 'Сохраняем...' : 'Изменить пароль'}
              </Btn>
            </div>
          </form>
        </Card>
      </Section>

      {/* Резервное копирование */}
      <Section title="Резервное копирование">
        <Card>
          <PanelHead><Download size={15} /> Backup настроек</PanelHead>
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ fontSize: 13, color: 'var(--ink-dim)', lineHeight: 1.6 }}>
              Экспортируй настройки всех плагинов в JSON. После обновления системы — импортируй,
              и API ключи, токены, категории qBittorrent, белый список и команды бота восстановятся.
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div style={{ background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 'var(--r)', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ fontWeight: 600, fontSize: 13, fontFamily: 'var(--mono)' }}>Экспорт</div>
                <div style={{ fontSize: 12, color: 'var(--ink-faint)' }}>Скачать backup JSON</div>
                <Btn variant="primary" onClick={exportSettings} disabled={exporting} style={{ marginTop: 'auto' }}>
                  {exporting ? <Spinner size={13} /> : <Download size={13} />}
                  {exporting ? 'Экспорт...' : 'Скачать'}
                </Btn>
              </div>

              <div style={{ background: 'var(--panel)', border: '1px solid var(--line)', borderRadius: 'var(--r)', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ fontWeight: 600, fontSize: 13, fontFamily: 'var(--mono)' }}>Импорт</div>
                <div style={{ fontSize: 12, color: 'var(--ink-faint)' }}>Загрузить backup JSON</div>
                <div style={{ marginTop: 'auto' }}>
                  <Btn
                    variant="default"
                    disabled={importing}
                    onClick={() => !importing && fileRef.current?.click()}
                    style={{ width: '100%', justifyContent: 'center', cursor: importing ? 'not-allowed' : 'pointer' }}
                  >
                    {importing ? <Spinner size={13} /> : <Upload size={13} />}
                    {importing ? 'Импорт...' : 'Загрузить'}
                  </Btn>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".json"
                    style={{ display: 'none' }}
                    onChange={e => { importSettings(e.target.files[0]); e.target.value = '' }}
                  />
                </div>
              </div>
            </div>

            {importResult && (
              <div style={{
                padding: '12px 14px', borderRadius: 'var(--r)',
                background: importResult.status === 'ok' ? 'var(--green-dim)' : importResult.status === 'partial' ? 'var(--amber-dim)' : 'var(--red-dim)',
                border: `1px solid ${importResult.status === 'ok' ? 'var(--green)' : importResult.status === 'partial' ? 'var(--amber)' : 'var(--red)'}`,
                display: 'flex', gap: 10, alignItems: 'flex-start',
              }}>
                {importResult.status === 'ok'
                  ? <CheckCircle size={16} style={{ color: 'var(--green)', flexShrink: 0, marginTop: 1 }} />
                  : <AlertCircle size={16} style={{ color: importResult.status === 'partial' ? 'var(--amber)' : 'var(--red)', flexShrink: 0, marginTop: 1 }} />
                }
                <div style={{ fontSize: 13 }}>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>{importResult.message}</div>
                  {importResult.restored?.length > 0 &&
                    <div style={{ color: 'var(--ink-dim)', fontSize: 12, marginBottom: 2 }}>✓ Восстановлено: {importResult.restored.join(', ')}</div>}
                  {importResult.restarted?.length > 0 &&
                    <div style={{ color: 'var(--ink-dim)', fontSize: 12, marginBottom: 2 }}>🔄 Перезапущено: {importResult.restarted.join(', ')}</div>}
                  {importResult.skipped?.length > 0 &&
                    <div style={{ color: 'var(--ink-faint)', fontSize: 12, marginBottom: 2 }}>⚠ Пропущено: {importResult.skipped.join(', ')}</div>}
                  {importResult.errors?.length > 0 &&
                    <div style={{ color: 'var(--red)', fontSize: 12, marginTop: 4 }}>❌ {importResult.errors.join('; ')}</div>}
                </div>
              </div>
            )}

            <div style={{ fontSize: 11, color: 'var(--ink-faint)', lineHeight: 1.5 }}>
              ⚠️ Плагины должны быть установлены до импорта. Маскированные токены (•••) не затираются. Плагины автоматически перезапускаются после восстановления настроек.
            </div>
          </div>
        </Card>
      </Section>
    </div>
  )
}