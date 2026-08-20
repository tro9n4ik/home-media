// Копирует собранный React из dist/ в core/app/web/static/admin
// для локального запуска ядра без Docker.
// Использование: npm run build:sync
import { cpSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

const src = resolve('dist')
const dst = resolve('../core/app/web/static/admin')

mkdirSync(dst, { recursive: true })
cpSync(src, dst, { recursive: true, force: true })
console.log(`[sync] React собран → ${dst}`)