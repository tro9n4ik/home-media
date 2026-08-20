import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LogIn } from 'lucide-react'
import { api } from '../lib/api'
import { Btn, Spinner } from '../components/ui'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)
  const nav = useNavigate()

  const submit = async (e) => {
    e.preventDefault()
    setError(''); setLoading(true)
    try {
      await api.login({ username, password })
      nav('/admin/')
    } catch (err) {
      setError(err.message)
    }
    setLoading(false)
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg)' }}>
      <div className="panel-card" style={{
        width: 380, padding: '40px 34px', animation: 'fadeUp .35s', background: 'var(--panel)',
      }}>
        <div style={{ textAlign: 'center', marginBottom: 30 }}>
          <div style={{
            width: 56, height: 56, borderRadius: 16, margin: '0 auto 16px',
            background: 'var(--primary-container)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: 'var(--disp)', fontWeight: 500, fontSize: 22, color: 'var(--on-primary-container)',
          }}>HM</div>
          <div style={{ fontFamily: 'var(--disp)', fontSize: 22, fontWeight: 400 }}>
            Home.Media
          </div>
          <div style={{ fontSize: 13, color: 'var(--ink-faint)', marginTop: 8 }}>
            панель управления · войдите для продолжения
          </div>
        </div>

        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <input placeholder="логин" value={username}
            onChange={e => setUsername(e.target.value)} autoFocus />
          <input type="password" placeholder="пароль" value={password}
            onChange={e => setPassword(e.target.value)} />

          {error && (
            <div className="errbox" style={{ justifyContent: 'flex-start' }}>
              {error}
            </div>
          )}

          <Btn variant="primary" disabled={loading} style={{ width: '100%', justifyContent: 'center', marginTop: 6, padding: '11px 18px' }}>
            {loading ? <Spinner size={15} /> : <LogIn size={15} />}
            {loading ? 'Вход...' : 'Войти'}
          </Btn>
        </form>
      </div>
    </div>
  )
}