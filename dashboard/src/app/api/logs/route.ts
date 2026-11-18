import { NextResponse } from 'next/server'
import { existsSync } from 'fs'
import { requireOwner } from '@/lib/auth'
import { type LogEntry } from '@/lib/logMonitor'
import { LOGS_DIR, listLogFiles, readLogEntries } from '@/lib/logFiles'

interface LogsResponse {
  logs: LogEntry[]
  totalCount: number
  availableFiles: string[]
  filters: {
    levels: string[]
    dateRange: { start: string; end: string }
  }
}

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url)

    // Get filter parameters
    const level = searchParams.get('level') // ERROR, WARNING, INFO, etc.
    const search = searchParams.get('search') // keyword search
    const startDate = searchParams.get('startDate')
    const endDate = searchParams.get('endDate')
    const limit = parseInt(searchParams.get('limit') || '1000')
    const files = searchParams.get('files')?.split(',') // specific files to read

    if (!existsSync(LOGS_DIR)) {
      return NextResponse.json({
        logs: [],
        totalCount: 0,
        availableFiles: [],
        filters: {
          levels: [],
          dateRange: { start: '', end: '' },
        },
        error: 'Logs directory not found',
      })
    }

    // Most recent first
    const logFiles = (await listLogFiles()).map(f => f.name)

    // Filter by date range if specified
    let filesToRead = logFiles
    if (startDate || endDate) {
      filesToRead = logFiles.filter(filename => {
        const dateMatch = filename.match(/(\d{4}-\d{2}-\d{2})/)
        if (!dateMatch) return false
        const fileDate = dateMatch[1]

        if (startDate && fileDate < startDate) return false
        if (endDate && fileDate > endDate) return false
        return true
      })
    }

    // If specific files requested, use those
    if (files && files.length > 0) {
      filesToRead = files.filter(f => logFiles.includes(f))
    }

    const needle = search?.toLowerCase()
    const allLogs = (await readLogEntries(filesToRead)).filter(entry => {
      if (level && entry.level !== level) return false
      if (needle && !entry.message.toLowerCase().includes(needle) && !entry.details?.toLowerCase().includes(needle)) return false
      return true
    })

    // Sort by timestamp (most recent first)
    allLogs.sort((a, b) => b.timestamp.localeCompare(a.timestamp))

    // Apply limit
    const limitedLogs = allLogs.slice(0, limit)

    // Get available log levels
    const levels = [...new Set(allLogs.map(log => log.level))].sort()

    // Get date range
    const timestamps = allLogs.map(log => log.timestamp).filter(Boolean)
    const dateRange = {
      start: timestamps.length > 0 ? timestamps[timestamps.length - 1].split(' ')[0] : '',
      end: timestamps.length > 0 ? timestamps[0].split(' ')[0] : '',
    }

    return NextResponse.json<LogsResponse>({
      logs: limitedLogs,
      totalCount: allLogs.length,
      availableFiles: logFiles,
      filters: {
        levels,
        dateRange,
      },
    })
  } catch (error) {
    console.error('Error reading logs:', error)
    return NextResponse.json(
      { error: 'Failed to read log files', details: String(error) },
      { status: 500 }
    )
  }
}
