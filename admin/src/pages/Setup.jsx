import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { UserPlus } from 'lucide-react'
import { api } from '../lib/api'
import { Btn, inputStyle, Spinner } from '../components/ui'

export default function Setup() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)
  const nav = useNavigate()

  const submit = async (e) => {
    e.preventDefault()
    const u = username.trim()
    if (!u)               { setError('Введите логин'); return }
    if (password.length < 8) { setError('Пароль минимум 8 символов'); return }

    setError(''); setLoading(true)
    try {
      await api.setup({ username: u, password })
      await api.login({ username: u, password })
      nav('/admin/')
    } catch (err) {
      setError(err.message || 'Не удалось создать аккаунт')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
      <div className="panel-card" style={{
        width: 400, padding: '32px 28px', animation: 'fadeIn .2s', background: 'var(--panel)',
      }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div style={{
            width: 52, height: 52, borderRadius: 10, margin: '0 auto 14px',
            background: 'var(--panel-raised)', border: '1px solid var(--line)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: 'var(--mono)', fontWeight: 700, fontSize: 18, color: 'var(--amber)',
          }}>HM</div>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 15, fontWeight: 600, letterSpacing: '.06em', textTransform: 'uppercase' }}>
            Первичная настройка
          </div>
          <div style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-faint)', marginTop: 6, letterSpacing: '.08em' }}>
            CREATE ADMIN ACCOUNT
          </div>
        </div>

        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <input
            style={inputStyle} placeholder="логин"
            value={username} onChange={e => setUsername(e.target.value)}
            autoFocus autoComplete="username"
          />
          <input
            style={inputStyle} type="password"
            placeholder="пароль (мин. 8 символов)"
            value={password} onChange={e => setPassword(e.target.value)}
            autoComplete="new-password"
          />

          {error && (
            <div className="errbox" style={{ justifyContent: 'flex-start' }}>
              {error}
            </div>
          )}

          <Btn
            variant="primary"
            disabled={loading || !username || !password}
            style={{ width: '100%', justifyContent: 'center', marginTop: 4 }}
          >
            {loading ? <Spinner size={14} /> : <UserPlus size={14} />}
            {loading ? 'Создаём...' : 'Начать'}
          </Btn>
        </form>
      </div>
    </div>
  )
}