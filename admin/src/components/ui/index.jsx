import { Loader2 } from 'lucide-react'

export function Spinner({ size = 20 }) {
  return (
    <Loader2 size={size} style={{
      animation: 'spin .7s linear infinite',
      color: 'var(--amber)',
      flexShrink: 0,
    }} />
  )
}

export function Btn({ children, variant = 'default', size = 'md', onClick, disabled, style, type }) {
  return (
    <button
      type={type}
      className={`btn ${variant === 'primary' ? 'primary' : ''} ${variant === 'danger' ? 'danger' : ''} ${variant === 'success' ? 'success' : ''} ${variant === 'ghost' ? 'ghost' : ''} ${size === 'sm' ? 'sm' : ''}`}
      onClick={onClick}
      disabled={disabled}
      style={style}
    >
      {children}
    </button>
  )
}

export function Card({ children, style, onClick }) {
  return (
    <div
      className="panel-card"
      onClick={onClick}
      style={{
        cursor: onClick ? 'pointer' : undefined,
        transition: onClick ? 'border-color .15s, transform .15s' : undefined,
        ...style,
      }}
    >
      {children}
    </div>
  )
}

export function Badge({ children, color = 'gray' }) {
  const cls = {
    green: 'st-run', yellow: 'st-deg', red: 'st-err', gray: 'st-off',
  }[color] || 'st-off'
  if (Array.isArray(children) || typeof children === 'string') {
    return <span className={`status-tag ${cls}`}><span className="d" />{children}</span>
  }
  return <span className={`status-tag ${cls}`}>{children}</span>
}

export function StatusDot({ status }) {
  const cls = {
    running: 'var(--green)',
    starting: 'var(--amber)',
    degraded: 'var(--amber)',
    installing: 'var(--amber)',
    stopped: 'var(--ink-faint)',
    installed: 'var(--ink-faint)',
    failed: 'var(--red)',
    error: 'var(--red)',
  }
  const c = cls[status] || 'var(--ink-faint)'
  return (
    <span style={{
      display: 'inline-block', width: 6, height: 6, borderRadius: '50%',
      background: c, flexShrink: 0,
      boxShadow: status === 'running' ? '0 0 6px var(--green)' : undefined,
    }} />
  )
}

export function Empty({ icon, text }) {
  return (
    <div style={{ textAlign: 'center', padding: '48px 20px', color: 'var(--ink-faint)', animation: 'fadeUp .25s' }}>
      {icon && <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'center', opacity: .4 }}>{icon}</div>}
      <div style={{ fontSize: 13.5, fontFamily: 'var(--mono)' }}>{text}</div>
    </div>
  )
}

export function Field({ label, hint, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      {label && <label style={{ fontSize: 11, color: 'var(--ink-dim)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.06em', fontFamily: 'var(--mono)' }}>{label}</label>}
      {children}
      {hint && <div style={{ fontSize: 11, color: 'var(--ink-faint)' }}>{hint}</div>}
    </div>
  )
}

export const inputStyle = {
  width: '100%',
}

// Секция с баром
export function Section({ title, right, children }) {
  return (
    <div>
      <div className="sec-label"><span className="bar" /><span>{title}</span>{right && <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--ink-faint)', fontFamily: 'var(--mono)' }}>{right}</span>}</div>
      {children}
    </div>
  )
}

let _tc = null
export function showToast(msg, type = 'ok', dur = 3000) {
  if (!_tc) {
    _tc = document.createElement('div')
    _tc.style.cssText = 'position:fixed;bottom:24px;right:24px;display:flex;flex-direction:column;gap:10px;z-index:9999'
    document.body.appendChild(_tc)
  }
  const colors = { ok: 'var(--green)', err: 'var(--red)', info: 'var(--amber)' }
  const c = colors[type] || colors.info
  const t = document.createElement('div')
  t.style.cssText = `
    padding:12px 18px;border-radius:10px;font-size:12.5px;font-weight:500;
    font-family:var(--mono);color:var(--ink);background:var(--panel-raised);
    border:1px solid ${c};box-shadow:var(--shadow);
    animation:toastIn .2s;border-left:3px solid ${c};max-width:360px;
  `
  t.textContent = msg
  _tc.appendChild(t)
  setTimeout(() => {
    t.style.transition = 'opacity .25s, transform .25s'
    t.style.opacity = '0'
    t.style.transform = 'translateY(8px)'
    setTimeout(() => t.remove(), 260)
  }, dur)
}