/**
 * PluginPage — универсальный рендерер плагинов через iframe.
 *
 * Плагин отдаёт свой UI через GET /ui/ — ядро просто монтирует iframe.
 * Никакого React в плагине не нужно. Полная изоляция CSS/JS.
 *
 * Коммуникация:
 *   ядро → плагин: postMessage({ type: 'hm:theme', theme: 'dark'|'light' })
 *   плагин → ядро: postMessage({ type: 'hm:toast', message: '...' })
 *                  postMessage({ type: 'hm:title', title: '...' })
 */
import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { Loader2, AlertCircle, ExternalLink } from 'lucide-react'
import { api } from '../lib/api'
import { Badge, StatusDot, Btn, showToast } from '../components/ui'

export default function PluginPage() {
  const { pluginId }    = useParams()
  const [plugin, setPlugin]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [iframeReady, setIframeReady] = useState(false)
  const iframeRef = useRef(null)

  const theme = 'dark'

  const pluginUiUrl = `/api/plugins/${pluginId}/proxy/ui/?theme=${theme}`

  useEffect(() => {
    api.pluginGet(pluginId)
      .then(p => { setPlugin(p); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [pluginId])

  useEffect(() => {
    const handler = (e) => {
      if (!e.data?.type?.startsWith('hm:')) return
      switch (e.data.type) {
        case 'hm:toast':
          showToast(e.data.message, e.data.variant || 'ok')
          break
        case 'hm:ready':
          setIframeReady(true)
          iframeRef.current?.contentWindow?.postMessage(
            { type: 'hm:theme', theme },
            '*'
          )
          break
      }
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [theme])

  if (loading) return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
      <Loader2 size={28} color="var(--amber)" style={{ animation: 'spin .7s linear infinite' }} />
    </div>
  )

  if (error) return (
    <div style={{ padding: 40, textAlign: 'center', color: 'var(--red)' }}>
      <AlertCircle size={40} style={{ margin: '0 auto 12px', opacity: .6 }} />
      <div style={{ fontFamily: 'var(--mono)' }}>{error}</div>
    </div>
  )

  if (plugin?.status !== 'running') return (
    <div style={{ animation: 'fadeIn .2s' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24 }}>
        <h1 style={{ fontSize: 18, fontWeight: 600, margin: 0, fontFamily: 'var(--mono)' }}>{plugin?.name}</h1>
        <Badge color="gray">v{plugin?.version}</Badge>
        <StatusDot status={plugin?.status} />
        <span style={{ fontSize: 12, color: 'var(--ink-faint)', fontFamily: 'var(--mono)' }}>{plugin?.status}</span>
      </div>
      <div className="panel-card" style={{
        padding: '48px 32px', textAlign: 'center', color: 'var(--ink-faint)',
      }}>
        <AlertCircle size={40} style={{ margin: '0 auto 16px', opacity: .3 }} />
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, fontFamily: 'var(--mono)', color: 'var(--ink)' }}>Плагин не запущен</div>
        <div style={{ fontSize: 13 }}>Запустите плагин на странице «Плагины»</div>
      </div>
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0, animation: 'fadeIn .2s', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <h1 style={{ fontSize: 18, fontWeight: 600, margin: 0, fontFamily: 'var(--mono)' }}>{plugin?.name}</h1>
        <Badge color="gray">v{plugin?.version}</Badge>
        <StatusDot status={plugin?.status} />
        <div style={{ flex: 1 }} />
        <Btn size="sm" variant="ghost"
          onClick={() => window.open(pluginUiUrl, '_blank')}
          style={{ color: 'var(--ink-faint)' }}>
          <ExternalLink size={13} /> Открыть отдельно
        </Btn>
      </div>

      <div style={{ position: 'relative', flex: 1 }}>
        {!iframeReady && (
          <div style={{
            position: 'absolute', inset: 0, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            background: 'var(--panel)', borderRadius: 'var(--r-lg)',
          }}>
            <Loader2 size={24} color="var(--amber)" style={{ animation: 'spin .7s linear infinite' }} />
          </div>
        )}
        <iframe
          ref={iframeRef}
          src={pluginUiUrl}
          onLoad={() => setIframeReady(true)}
          style={{
            width: '100%',
            height: 'calc(100vh - 140px)',
            minHeight: 500,
            border: '1px solid var(--line)',
            borderRadius: 'var(--r-lg)',
            background: 'var(--bg)',
            display: iframeReady ? 'block' : 'block',
          }}
          title={plugin?.name}
        />
      </div>
    </div>
  )
}