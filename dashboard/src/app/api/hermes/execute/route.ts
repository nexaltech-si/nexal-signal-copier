import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { requireOwner } from '@/lib/auth'

// Execute a Hermes IDEA setup as a REAL order via the MT5 REST API.
// Clerk-protected (browser only). Places market when price is in the zone,
// pending limit when away. SL mandatory. Tags orders with a Hermes magic number.
const MT5 = process.env.MT5_REST_API_URL
const KEY = process.env.MT5_REST_API_KEY
const MAGIC = 770077 // Hermes-tagged orders (isolated from the channel bot)

async function tick(symbol: string): Promise<{ bid: number; ask: number } | null> {
  const h: Record<string, string> = KEY ? { 'X-API-Key': KEY } : {}
  const c = new AbortController(); const t = setTimeout(() => c.abort(), 5000)
  try {
    const r = await fetch(`${MT5}/symbol_info_tick/${symbol}`, { headers: h, signal: c.signal })
    clearTimeout(t); if (!r.ok) return null
    const j = await r.json()
    if (typeof j.bid !== 'number' || typeof j.ask !== 'number') return null
    return { bid: j.bid, ask: j.ask }
  } catch { clearTimeout(t); return null }
}

export async function POST(req: NextRequest) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    if (!MT5) return NextResponse.json({ error: 'MT5_REST_API_URL not configured' }, { status: 500 })
    const { id, lot, tpIndex } = await req.json()
    const volume = parseFloat(lot)
    if (!id || !(volume > 0)) return NextResponse.json({ error: 'id and a positive lot are required' }, { status: 400 })

    const s = await prisma.hermesSetup.findUnique({ where: { id } })
    if (!s) return NextResponse.json({ error: 'setup not found' }, { status: 404 })
    if (s.status !== 'IDEA') return NextResponse.json({ error: `setup is ${s.status} — only IDEA setups can be executed` }, { status: 400 })
    if (s.sl == null) return NextResponse.json({ error: 'SAFETY BLOCK: setup has no stop loss' }, { status: 400 })

    const tps: number[] = s.tps ? JSON.parse(s.tps) : []
    const tpi = Number.isInteger(tpIndex) ? tpIndex : 0
    const tp = tps[tpi] ?? tps[0] ?? null
    const isBuy = s.bias === 'BUY'
    const entry = s.entryMin ?? null

    const px = await tick(s.symbol)
    if (!px) return NextResponse.json({ error: 'could not fetch price (market data unavailable / closed)' }, { status: 502 })
    const cur = isBuy ? px.ask : px.bid

    // market when price already at/through entry, else pending limit
    let market = false, pendingType = ''
    if (entry == null) market = true
    else if (isBuy) { if (cur <= entry) market = true; else pendingType = 'BUY_LIMIT' }
    else { if (cur >= entry) market = true; else pendingType = 'SELL_LIMIT' }

    const headers: Record<string, string> = { 'content-type': 'application/json' }
    if (KEY) headers['X-API-Key'] = KEY
    const comment = `hermes-${s.setupType}`.slice(0, 31)

    let path: string, body: Record<string, unknown>
    if (market) {
      path = '/order'
      body = { symbol: s.symbol, volume, type: isBuy ? 'BUY' : 'SELL', deviation: 20, magic: MAGIC, comment, sl: s.sl }
      if (tp) body.tp = tp
    } else {
      path = '/limit_order'
      body = { symbol: s.symbol, volume, type: pendingType, price: entry, magic: MAGIC, comment, type_filling: 'ORDER_FILLING_RETURN', sl: s.sl }
      if (tp) body.tp = tp
    }

    const c = new AbortController(); const t = setTimeout(() => c.abort(), 15000)
    let resp: Response
    try {
      resp = await fetch(`${MT5}${path}`, { method: 'POST', headers, body: JSON.stringify(body), signal: c.signal })
    } catch (e: any) { clearTimeout(t); return NextResponse.json({ error: `MT5 unreachable: ${e?.message}` }, { status: 502 }) }
    clearTimeout(t)

    const textBody = await resp.text()
    let j: any = {}; try { j = JSON.parse(textBody) } catch {}
    if (!resp.ok) return NextResponse.json({ error: `MT5 rejected: ${resp.status} ${textBody.slice(0, 250)}` }, { status: 502 })

    const r = j.result || {}
    const order = r.order ?? null
    const deal = r.deal ?? null
    const ticket = deal || order
    const newStatus = deal ? 'OPEN' : 'PLACED'
    await prisma.hermesSetup.update({ where: { id }, data: { status: newStatus } })
    await prisma.hermesSetupEvent.create({
      data: {
        setupId: id, eventType: 'EXECUTED', price: cur,
        note: `${market ? 'MARKET' : 'PENDING'} ${isBuy ? 'BUY' : 'SELL'} ${volume} @ ${market ? cur : entry} · sl=${s.sl}${tp ? ` · tp=${tp}` : ''} · ticket=${ticket} · ${newStatus}`,
      },
    })
    return NextResponse.json({ ok: true, status: newStatus, ticket, order, deal, market, message: j.message || 'submitted' })
  } catch (e: any) {
    return NextResponse.json({ error: e?.message ?? 'failed' }, { status: 500 })
  }
}
