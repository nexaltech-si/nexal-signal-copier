import { NextResponse } from 'next/server'
import { getAllJournalEntries } from '@/lib/trade-journal-store'
import { requireOwner } from '@/lib/auth'

export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const entries = await getAllJournalEntries()
    return NextResponse.json(entries, {
      headers: {
        'Cache-Control': 'private, max-age=60, stale-while-revalidate=300',
      },
    })
  } catch (error) {
    console.error('Error fetching journal entries:', error)
    return NextResponse.json(
      { error: 'Failed to fetch journal entries' },
      { status: 500 }
    )
  }
}
