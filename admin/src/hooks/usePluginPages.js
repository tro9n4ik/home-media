import { useState, useEffect, useRef } from 'react'
import { api } from '../lib/api'

// Глобальный кеш — один набор pages для всего приложения
let _pages = []
let _listeners = new Set()
let _intervalId = null

function subscribe(fn) {
  _listeners.add(fn)
  if (!_intervalId) {
    const load = () => api.uiPages().then(p => {
      _pages = p
      _listeners.forEach(f => f(p))
    }).catch(() => {})
    load()
    _intervalId = setInterval(load, 10_000)
  }
  return () => {
    _listeners.delete(fn)
    if (_listeners.size === 0 && _intervalId) {
      clearInterval(_intervalId)
      _intervalId = null
    }
  }
}

export function usePluginPages() {
  const [pages, setPages] = useState(_pages)

  useEffect(() => {
    setPages(_pages)
    return subscribe(setPages)
  }, [])

  return pages
}
