import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'
import { buildMonitor } from '@/lib/logMonitor'
import { listLogFiles, readLogEntries, recentFileNames, loadAcks, saveAcks } from '@/lib/logFiles'

const BOT_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

async function botOnline(): Promise<boolean> {
  try {
    const res = await fetch(`${BOT_API_URL}/health`, { cache: 'no-store', signal: AbortSignal.timeout(3000) })
    return res.ok
  } catch {
    return false
  }
}

// Health summary for the Monitor tab and the sidebar badge.
export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const [files, acks, online] = await Promise.all([listLogFiles(), loadAcks(), botOnline()])
    const entries = await readLogEntries(recentFileNames(files, 1))
    const summary = buildMonitor(entries, { acks })
    // ?summary=1: headline only, for the sidebar dot.
    if (new URL(request.url).searchParams.get('summary')) {
      const { status, statusReason, totals } = summary
      return NextResponse.json({ status, statusReason, totals, botOnline: online })
    }
    return NextResponse.json({
      ...summary,
      botOnline: online,
      files,
      totalBytes: files.reduce((n, f) => n + f.size, 0),
    })
  } catch (error) {
    console.error('Error building log monitor:', error)
    return NextResponse.json({ error: 'Failed to read log files', details: String(error) }, { status: 500 })
  }
}

// Acknowledge / mute / reopen an issue. Body: { signature, action: 'ack' | 'mute' | 'reopen' }
export async function POST(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  const { signature: sig, action } = await request.json().catch(() => ({}))
  if (typeof sig !== 'string' || !sig || !['ack', 'mute', 'reopen'].includes(action)) {
    return NextResponse.json({ error: 'signature and action (ack|mute|reopen) required' }, { status: 400 })
  }

  const acks = await loadAcks()
  if (action === 'reopen') delete acks[sig]
  else acks[sig] = { at: new Date().toISOString(), ...(action === 'mute' ? { muted: true } : {}) }
  await saveAcks(acks)
  return NextResponse.json({ ok: true })
}
