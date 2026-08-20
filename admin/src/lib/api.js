const BASE = '/api'

async function request(path, opts = {}) {
  const { headers: extraHeaders, ...restOpts } = opts
  const res = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...extraHeaders },
    ...restOpts,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    // FastAPI 422 возвращает detail как массив [{loc, msg, type}]
    if (Array.isArray(data?.detail)) {
      const msg = data.detail.map(e => {
        const field = Array.isArray(e.loc) ? e.loc.slice(-1)[0] : 'field'
        return `${field}: ${e.msg}`
      }).join('; ')
      throw new Error(msg)
    }
    throw new Error(
      typeof data?.detail === 'string' ? data.detail :
      data?.message || res.statusText || 'Ошибка запроса'
    )
  }
  return res.json()
}

export const api = {
  // Auth
  setupNeeded: ()     => request('/auth/setup/needed'),
  setup:       (data) => request('/auth/setup',  { method: 'POST', body: JSON.stringify(data) }),
  login:       (data) => request('/auth/login',  { method: 'POST', body: JSON.stringify(data) }),
  logout:      ()     => request('/auth/logout', { method: 'POST' }),
  me:          ()     => request('/auth/me'),
  changePassword: (data) => request('/auth/change-password', { method: 'POST', body: JSON.stringify(data) }),

  // System
  metrics:     ()     => request('/system/metrics'),
  uiPages:     ()     => request('/system/ui-pages'),
  registry:    ()     => request('/system/registry'),

  // Plugins
  plugins:       ()          => request('/plugins'),
  pluginGet:     (id)        => request(`/plugins/${id}`),
  pluginInstall: (file)      => {
    const fd = new FormData()
    fd.append('file', file)
    return fetch(`${BASE}/plugins/install`, {
      method: 'POST', credentials: 'include', body: fd,
    }).then(async r => {
      if (!r.ok) {
        const data = await r.json().catch(() => null)
        throw new Error(
          Array.isArray(data?.detail) ? data.detail.map(e => e.msg).join('; ') :
          data?.detail || r.statusText
        )
      }
      return r.json()
    })
  },
  pluginStart:      (id)        => request(`/plugins/${id}/start`,   { method: 'POST' }),
  pluginStop:       (id)        => request(`/plugins/${id}/stop`,    { method: 'POST' }),
  pluginRestart:    (id)        => request(`/plugins/${id}/restart`, { method: 'POST' }),
  pluginEnable:     (id)        => request(`/plugins/${id}/enable`,  { method: 'POST' }),
  pluginDisable:    (id)        => request(`/plugins/${id}/disable`, { method: 'POST' }),
  pluginDelete:     (id)        => request(`/plugins/${id}`,         { method: 'DELETE' }),
  pluginConnection: (id)        => request(`/plugins/${id}/connection`),

  // Plugin proxy
  pluginProxy: (id, path, opts = {}) => request(`/plugins/${id}/proxy/${path}`, opts),

  // Logs
  pluginLogs:  (id, lines = 200) => request(`/system/logs/${id}?lines=${lines}`),
  allLogs:     (lines = 100)     => request(`/system/logs?lines=${lines}`),

  // Settings backup
  exportSettings: () => fetch('/api/system/settings/export', { credentials: 'include' })
    .then(r => r.ok ? r.blob() : r.json().then(e => Promise.reject(new Error(e.detail)))),
  importSettings: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return fetch('/api/system/settings/import', {
      method: 'POST', credentials: 'include', body: fd,
    }).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(new Error(e.detail))))
  },
}
