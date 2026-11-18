import { NextResponse } from 'next/server'
import { readFile } from 'fs/promises'
import { join } from 'path'
import { existsSync } from 'fs'
import { requireOwner } from '@/lib/auth'

export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const cacheFile = join(process.cwd(), 'data', 'news_cache.json')

    if (!existsSync(cacheFile)) {
      return NextResponse.json({ events: [], source: 'empty' })
    }

    const raw = await readFile(cacheFile, 'utf-8')
    const events = JSON.parse(raw)

    return NextResponse.json({ events, source: 'cache' })
  } catch {
    return NextResponse.json({ error: 'Failed to read news cache' }, { status: 500 })
  }
}