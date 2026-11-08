// Dependency-free CDP helper for the owned Electron stability harness.
import { createInterface } from 'node:readline'

async function call(port, method, params = {}, main = false) {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
  const target = main ? targets[0] : targets.find((item) => item.type === 'page' && !item.url.startsWith('devtools:'))
  if (!target) throw new Error('Owned Electron CDP target is not ready')
  const ws = new WebSocket(target.webSocketDebuggerUrl)
  return await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { ws.close(); reject(new Error('CDP deadline exceeded')) }, 30000)
    ws.onopen = () => ws.send(JSON.stringify({ id: 1, method, params }))
    ws.onerror = () => { clearTimeout(timeout); reject(new Error('CDP connection failed')) }
    ws.onmessage = ({ data }) => {
      const result = JSON.parse(data)
      if (result.id !== 1) return
      clearTimeout(timeout)
      ws.close()
      if (result.error || result.result?.exceptionDetails) reject(new Error(JSON.stringify(result.error || result.result.exceptionDetails)))
      else resolve(result.result)
    }
  })
}

for await (const line of createInterface({ input: process.stdin, crlfDelay: Infinity })) {
  try {
    const item = JSON.parse(line)
    const result = await call(item.port, item.method || 'Runtime.evaluate', item.params || {
      expression: item.expression, awaitPromise: true, returnByValue: true,
    }, item.main)
    process.stdout.write(`${JSON.stringify({ ok: true, result })}\n`)
  } catch (error) {
    process.stdout.write(`${JSON.stringify({ ok: false, error: String(error) })}\n`)
  }
}
