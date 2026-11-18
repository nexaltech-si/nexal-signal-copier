// Prisma-backed store for trade journal notes and tags
// Replaces the old file-based JSON store — data now survives restarts

import { prisma } from '@/lib/prisma'

type JournalEntry = {
  notes: string
  tags: string[]
}

type JournalStore = {
  [tradeId: string]: JournalEntry
}

function parseTags(raw: string): string[] {
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export async function getJournalEntry(tradeId: string): Promise<JournalEntry | null> {
  const row = await prisma.journalEntry.findUnique({ where: { tradeId } })
  if (!row) return null
  return { notes: row.notes, tags: parseTags(row.tags) }
}

export async function getAllJournalEntries(): Promise<JournalStore> {
  const rows = await prisma.journalEntry.findMany()
  const store: JournalStore = {}
  for (const row of rows) {
    store[row.tradeId] = { notes: row.notes, tags: parseTags(row.tags) }
  }
  return store
}

export async function updateJournalEntry(
  tradeId: string,
  data: { notes?: string; tags?: string[] }
): Promise<JournalEntry> {
  const existing = await prisma.journalEntry.findUnique({ where: { tradeId } })

  const newNotes = data.notes !== undefined ? data.notes : (existing?.notes ?? '')
  const newTags = data.tags !== undefined ? data.tags : parseTags(existing?.tags ?? '[]')

  const row = await prisma.journalEntry.upsert({
    where: { tradeId },
    create: {
      tradeId,
      notes: newNotes,
      tags: JSON.stringify(newTags),
    },
    update: {
      notes: newNotes,
      tags: JSON.stringify(newTags),
    },
  })

  return { notes: row.notes, tags: parseTags(row.tags) }
}