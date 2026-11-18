import { readdir, readFile, stat, writeFile, rename } from 'fs/promises'
import { existsSync } from 'fs'
import { join } from 'path'
import { parseLogContent, type AckRecord, type LogEntry } from '@/lib/logMonitor'

// Bot logs, mounted read-only at /app/logs. Acks live next to the shared DB, which is writable.
export const LOGS_DIR = join(process.cwd(), 'logs')
const ACKS_FILE = join(process.cwd(), 'data', 'log-monitor-acks.json')

export interface LogFileInfo {
  name: string
  size: number
  modified: string
}

export async function listLogFiles(): Promise<LogFileInfo[]> {
  if (!existsSync(LOGS_DIR)) return []
  const names = (await readdir(LOGS_DIR)).filter((f) => f.endsWith('.log')).sort().reverse()
  return Promise.all(
    names.map(async (name) => {
      const s = await stat(join(LOGS_DIR, name))
      return { name, size: s.size, modified: s.mtime.toISOString() }
    }),
  )
}

export async function readLogEntries(names: string[]): Promise<LogEntry[]> {
  const all: LogEntry[] = []
  for (const name of names) {
    const content = await readFile(join(LOGS_DIR, name), 'utf-8')
    all.push(...parseLogContent(content, name))
  }
  return all
}

/** Files that can hold entries from the last `days` days (date-stamped names). */
export function recentFileNames(files: LogFileInfo[], days: number, now = Date.now()): string[] {
  const cutoff = new Date(now - days * 86_400_000).toISOString().slice(0, 10)
  return files
    .map((f) => f.name)
    .filter((name) => {
      const d = name.match(/(\d{4}-\d{2}-\d{2})/)?.[1]
      return !d || d >= cutoff
    })
}

export async function loadAcks(): Promise<Record<string, AckRecord>> {
  try {
    return JSON.parse(await readFile(ACKS_FILE, 'utf-8'))
  } catch {
    return {}
  }
}

export async function saveAcks(acks: Record<string, AckRecord>): Promise<void> {
  const tmp = `${ACKS_FILE}.tmp`
  await writeFile(tmp, JSON.stringify(acks, null, 2))
  await rename(tmp, ACKS_FILE)
}
