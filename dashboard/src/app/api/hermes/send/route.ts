import { NextRequest } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

// Reads the EXISTING brain config from the settings table (never hardcoded/created).
async function getSetting(key: string, fallback = ''): Promise<string> {
  const s = await prisma.setting.findUnique({ where: { key } })
  return s?.value ?? fallback
}

type ChatMsg = { role: 'user' | 'assistant' | 'system'; content: string }

// POST /api/hermes/send  { message: string, history?: ChatMsg[] }
// Proxies to the Hermes brain (BRAIN_BASE_URL /v1/chat/completions) with SSE streaming.
// Streams tool progress + partial responses in real-time — same behaviour as Telegram chat.
export async function POST(req: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const body = await req.json()
    const message: string = body?.message
    if (!message || typeof message !== 'string') {
      return new Response(JSON.stringify({ error: 'message required' }), { status: 400 })
    }

    const base = (await getSetting('BRAIN_BASE_URL')).replace(/\/+$/, '')
    const key = await getSetting('BRAIN_API_KEY')
    const model = (await getSetting('BRAIN_MODEL')) || 'hermes'
    const temperature = parseFloat(await getSetting('BRAIN_TEMPERATURE', '1')) || 1
    const maxHistory = parseInt(await getSetting('BRAIN_MAX_HISTORY_MESSAGES', '60'), 10) || 60
    if (!base) {
      return new Response(JSON.stringify({ error: 'BRAIN_BASE_URL not configured in settings' }), { status: 500 })
    }

    const history: ChatMsg[] = Array.isArray(body?.history) ? body.history.slice(-maxHistory) : []
    const messages: ChatMsg[] = [...history, { role: 'user', content: message }]

    // ── SSE stream from Hermes ──────────────────────────────────────────
    const stream = new ReadableStream({
      async start(controller) {
        const encoder = new TextEncoder()
        const enqueue = (data: string) => controller.enqueue(encoder.encode(data))

        // 10-minute total timeout (no more 60s cut-offs)
        const ctrl = new AbortController()
        const timer = setTimeout(() => ctrl.abort(), 600_000)

        try {
          const r = await fetch(`${base}/v1/chat/completions`, {
            method: 'POST',
            headers: {
              'content-type': 'application/json',
              ...(key ? { Authorization: `Bearer ${key}` } : {}),
            },
            body: JSON.stringify({ model, messages, temperature, stream: true }),
            signal: ctrl.signal,
          })
          clearTimeout(timer)

          if (!r.ok) {
            const t = await r.text()
            enqueue(`data: ${JSON.stringify({ error: `brain responded ${r.status}`, detail: t.slice(0, 500) })}\n\n`)
            enqueue('data: [DONE]\n\n')
            controller.close()
            return
          }

          // Pipe Hermes SSE chunks → frontend SSE
          const reader = r.body?.getReader()
          if (!reader) {
            enqueue(`data: ${JSON.stringify({ error: 'no response body from brain' })}\n\n`)
            enqueue('data: [DONE]\n\n')
            controller.close()
            return
          }

          const decoder = new TextDecoder()
          let buffer = ''

          while (true) {
            const { done, value } = await reader.read()
            if (done) break

            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            // Keep the last partial line in the buffer
            buffer = lines.pop() || ''

            for (const line of lines) {
              const trimmed = line.trim()
              if (!trimmed) continue
              // Pass through ALL SSE chunks — data, event, id, etc.
              enqueue(`${trimmed}\n`)
            }
          }

          // Flush remaining buffer
          if (buffer.trim()) {
            enqueue(`${buffer.trim()}\n`)
          }

          enqueue('data: [DONE]\n\n')
          controller.close()
        } catch (e: any) {
          clearTimeout(timer)
          const reason = e?.name === 'AbortError' ? 'timeout after 10 min' : (e?.message ?? 'unreachable')
          enqueue(`data: ${JSON.stringify({ error: `brain unreachable: ${reason}` })}\n\n`)
          enqueue('data: [DONE]\n\n')
          controller.close()
        }
      },
    })

    return new Response(stream, {
      headers: {
        'content-type': 'text/event-stream',
        'cache-control': 'no-cache',
        'connection': 'keep-alive',
        'x-accel-buffering': 'no',  // disable nginx buffering
      },
    })
  } catch (e: any) {
    return new Response(JSON.stringify({ error: e?.message ?? 'failed' }), { status: 500 })
  }
}
