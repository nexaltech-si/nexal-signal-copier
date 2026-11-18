'use client'

import { useState, useEffect, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Card } from '@/components/ui/card'
import MobilePageHeader from '@/components/MobilePageHeader'
import { FilterBar, FilterItem } from '@/components/FilterBar'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import LogMonitor from '@/components/LogMonitor'
import { type LogEntry } from '@/lib/logMonitor'
import { Search, RefreshCw, Download, FileText, Activity, ChevronDown, ChevronRight } from 'lucide-react'

interface LogsData {
  logs: LogEntry[]
  totalCount: number
  availableFiles: string[]
  filters: {
    levels: string[]
    dateRange: { start: string; end: string }
  }
}

export default function LogsPage() {
  const [tab, setTab] = useState<'monitor' | 'raw'>('monitor')
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set())
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [availableFiles, setAvailableFiles] = useState<string[]>([])
  const [availableLevels, setAvailableLevels] = useState<string[]>([])
  
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  
  // Filters
  const [levelFilter, setLevelFilter] = useState<string>('ALL')
  const [searchFilter, setSearchFilter] = useState<string>('')
  const [startDateFilter, setStartDateFilter] = useState<string>('')
  const [endDateFilter, setEndDateFilter] = useState<string>('')
  const [limitFilter, setLimitFilter] = useState<string>('1000')
  const [selectedFiles, setSelectedFiles] = useState<string[]>([])
  
  // Auto-refresh
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [refreshInterval] = useState(5) // seconds

  const fetchLogs = useCallback(async () => {
    setLoading(true)
    setError(null)
    
    try {
      const params = new URLSearchParams()
      if (levelFilter && levelFilter !== 'ALL') params.append('level', levelFilter)
      if (searchFilter) params.append('search', searchFilter)
      if (startDateFilter) params.append('startDate', startDateFilter)
      if (endDateFilter) params.append('endDate', endDateFilter)
      if (limitFilter) params.append('limit', limitFilter)
      if (selectedFiles.length > 0 && selectedFiles[0] !== 'ALL') params.append('files', selectedFiles.join(','))
      
      const response = await fetch(`/api/logs?${params.toString()}`)
      if (!response.ok) throw new Error('Failed to fetch logs')
      
      const data: LogsData = await response.json()
      setLogs(data.logs || [])
      setTotalCount(data.totalCount || 0)
      setAvailableFiles(data.availableFiles || [])
      setAvailableLevels(data.filters?.levels || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [levelFilter, searchFilter, startDateFilter, endDateFilter, limitFilter, selectedFiles])

  useEffect(() => {
    if (tab === 'raw') fetchLogs()
  }, [fetchLogs, tab])

  useEffect(() => setExpandedRows(new Set()), [logs])

  // Auto-refresh effect
  useEffect(() => {
    if (!autoRefresh || tab !== 'raw') return
    
    const interval = setInterval(() => {
      fetchLogs()
    }, refreshInterval * 1000)
    
    return () => clearInterval(interval)
  }, [autoRefresh, refreshInterval, fetchLogs, tab])

  const showInLogs = (search: string) => {
    setLevelFilter('ALL')
    setSelectedFiles([])
    setSearchFilter(search)
    setTab('raw')
  }

  const toggleRow = (index: number) => setExpandedRows(prev => {
    const next = new Set(prev)
    if (next.has(index)) next.delete(index)
    else next.add(index)
    return next
  })

  const clearFilters = () => {
    setLevelFilter('ALL')
    setSearchFilter('')
    setStartDateFilter('')
    setEndDateFilter('')
    setSelectedFiles([])
  }

  const exportLogs = () => {
    const dataStr = JSON.stringify(logs, null, 2)
    const dataBlob = new Blob([dataStr], { type: 'application/json' })
    const url = URL.createObjectURL(dataBlob)
    const link = document.createElement('a')
    link.href = url
    link.download = `logs-export-${new Date().toISOString()}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'ERROR': return 'bg-red-500 text-white'
      case 'WARNING': return 'bg-yellow-500 text-black'
      case 'INFO': return 'bg-blue-500 text-white'
      case 'DEBUG': return 'bg-gray-500 text-white'
      case 'SUCCESS': return 'bg-green-500 text-white'
      default: return 'bg-gray-300 text-black'
    }
  }

  const getLevelIcon = (level: string) => {
    switch (level) {
      case 'ERROR': return '❌'
      case 'WARNING': return '⚠️'
      case 'INFO': return 'ℹ️'
      case 'DEBUG': return '🔍'
      case 'SUCCESS': return '✅'
      default: return '📝'
    }
  }

  return (
    <div className="flex flex-col min-h-full">
      <MobilePageHeader 
        title="Logs" 
        subtitle="System Events"
        hidden
        icon={<FileText className="h-5 w-5" />}
      />
      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <FileText className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col">
            <h1 className="text-sm font-bold text-foreground leading-none">Logs</h1>
            <p className="text-[10px] text-[#6b7288] font-bold uppercase tracking-wider mt-1">System Events</p>
          </div>
          <div className={cn('ml-auto flex items-center gap-2', tab !== 'raw' && 'hidden')}>
            <span className="text-xs text-muted-foreground font-semibold">{totalCount.toLocaleString()} entries</span>
            <Button variant={autoRefresh ? 'default' : 'outline'} size="sm" onClick={() => setAutoRefresh(!autoRefresh)} className="h-7 text-[10px] font-bold uppercase">
              <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${autoRefresh ? 'animate-spin' : ''}`} />
              Auto {autoRefresh && `(${refreshInterval}s)`}
            </Button>
            <Button variant="outline" size="sm" onClick={exportLogs} className="h-7 text-[10px] font-bold uppercase border-border">
              <Download className="w-3.5 h-3.5 mr-1.5" />Export
            </Button>
          </div>
        </div>
      </header>

      <Tabs value={tab} onValueChange={(v) => setTab(v as 'monitor' | 'raw')} className="flex-1 flex flex-col">
      <div className="sticky top-0 md:top-14 z-30 bg-card border-b border-border">
        <div className="max-w-[1800px] mx-auto px-3 md:px-6">
          <TabsList className="h-10 bg-transparent gap-0 p-0 rounded-none">
            {[
              { value: 'monitor', label: 'Monitor', icon: Activity },
              { value: 'raw', label: 'Raw logs', icon: FileText },
            ].map(t => (
              <TabsTrigger
                key={t.value}
                value={t.value}
                className="h-10 px-5 text-xs font-semibold rounded-none border-b-2 border-transparent
                  text-[#697188] data-[state=active]:text-primary data-[state=active]:border-primary
                  data-[state=active]:bg-transparent hover:text-foreground transition-colors"
              >
                <t.icon className="h-3.5 w-3.5 mr-1.5" />{t.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
      </div>

      {/* forceMount: keep an AI answer (paid tokens) when switching tabs */}
      <TabsContent value="monitor" forceMount className="data-[state=inactive]:hidden mt-0 flex-1 px-3 md:px-4 py-3 md:py-4 max-w-[1800px] mx-auto w-full">
        <LogMonitor onShowInLogs={showInLogs} />
      </TabsContent>

      <TabsContent value="raw" className="mt-0 flex-1 px-3 md:px-4 py-3 md:py-4 space-y-3 max-w-[1800px] mx-auto w-full">
      {/* Filters */}
      <FilterBar
        onReset={clearFilters}
        onApply={fetchLogs}
        showApplyButton
        loading={loading}
        hasActiveFilters={!!(levelFilter !== 'ALL' || searchFilter || startDateFilter || endDateFilter || selectedFiles.length > 0)}
      >
        <FilterItem label="Level">
          <Select value={levelFilter} onValueChange={setLevelFilter}>
            <SelectTrigger className="h-8">
              <SelectValue placeholder="All levels" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All levels</SelectItem>
              {availableLevels.map(level => (
                <SelectItem key={level} value={level}>
                  {getLevelIcon(level)} {level}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FilterItem>

        <FilterItem label="Search">
          <div className="relative">
            <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search logs..."
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              className="pl-8 h-8"
            />
          </div>
        </FilterItem>

        <FilterItem label="Start Date">
          <Input
            type="date"
            value={startDateFilter}
            onChange={(e) => setStartDateFilter(e.target.value)}
            className="h-8"
          />
        </FilterItem>

        <FilterItem label="End Date">
          <Input
            type="date"
            value={endDateFilter}
            onChange={(e) => setEndDateFilter(e.target.value)}
            className="h-8"
          />
        </FilterItem>

        <FilterItem label="Limit">
          <Select value={limitFilter} onValueChange={setLimitFilter}>
            <SelectTrigger className="h-8">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="100">100 entries</SelectItem>
              <SelectItem value="500">500 entries</SelectItem>
              <SelectItem value="1000">1,000 entries</SelectItem>
              <SelectItem value="5000">5,000 entries</SelectItem>
              <SelectItem value="10000">10,000 entries</SelectItem>
            </SelectContent>
          </Select>
        </FilterItem>

        <FilterItem label={`Files (${availableFiles.length})`}>
          <Select
            value={selectedFiles.length > 0 ? selectedFiles[0] : 'ALL'}
            onValueChange={(value) => setSelectedFiles(value === 'ALL' ? [] : [value])}
          >
            <SelectTrigger className="h-8">
              <SelectValue placeholder="All files (merged)" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All files (merged)</SelectItem>
              {availableFiles.map(file => (
                <SelectItem key={file} value={file}>{file}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FilterItem>
      </FilterBar>

      {error && (
        <Card className="p-4 bg-destructive/10 border-rose-300 shadow-sm">
          <p className="text-destructive font-semibold">Error: {error}</p>
        </Card>
      )}

      <Card className="p-4 bg-card border-border shadow-sm">
        {loading ? (
          <div className="text-center py-12 text-muted-foreground">
            <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-2" />
            <p className="font-semibold">Loading logs...</p>
          </div>
        ) : logs.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground">
            <p className="font-semibold">No logs found matching your filters</p>
          </div>
        ) : (
          <div className="space-y-1 font-mono text-xs max-h-[600px] overflow-y-auto">
            {logs.map((log, index) => (
              <div key={index}>
              <div
                onClick={log.details ? () => toggleRow(index) : undefined}
                className={cn(
                  "flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 py-2 sm:py-1.5 px-2 hover:bg-muted/50 rounded border-l-2",
                  log.details && "cursor-pointer"
                )}
                style={{
                  borderLeftColor: log.level === 'ERROR' ? 'rgb(239, 68, 68)' :
                                    log.level === 'WARNING' ? 'rgb(234, 179, 8)' :
                                    log.level === 'SUCCESS' ? 'rgb(34, 197, 94)' :
                                    'rgb(148, 163, 184)'
                }}
              >
                {/* Meta row - stacked on mobile, inline on desktop */}
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span className="text-muted-foreground whitespace-nowrap font-bold text-[10px] sm:text-xs">
                    {log.timestamp}
                  </span>
                  <span className={cn(
                    getLevelColor(log.level),
                    "inline-flex items-center justify-center w-[70px] sm:w-[80px] h-[18px] sm:h-[22px] flex-shrink-0 rounded-full text-[9px] sm:text-[10px] font-black uppercase tracking-tight"
                  )}>
                    {log.level}
                  </span>
                  {log.file && (
                    <span className="sm:hidden text-[9px] text-muted-foreground/70 font-bold bg-muted px-1.5 py-0.5 rounded truncate max-w-[100px]">
                      {log.file}
                    </span>
                  )}
                </div>

                {/* Message block */}
                <span className="flex-1 break-words text-foreground leading-relaxed text-[11px] sm:text-xs ml-0 sm:ml-0 px-1 sm:px-0">
                  {log.details && (expandedRows.has(index)
                    ? <ChevronDown className="inline h-3 w-3 mr-1 text-muted-foreground" />
                    : <ChevronRight className="inline h-3 w-3 mr-1 text-muted-foreground" />)}
                  {log.message}
                </span>

                {/* File info (Desktop only) */}
                {log.file && (
                  <span className="hidden sm:block text-[10px] text-muted-foreground/70 whitespace-nowrap font-bold">
                    {log.file}
                  </span>
                )}
              </div>
              {log.details && expandedRows.has(index) && (
                <pre className="ml-4 mb-1 p-2 bg-muted/50 rounded text-[10px] overflow-x-auto whitespace-pre">{log.details}</pre>
              )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="p-4 bg-card border-border shadow-sm">
        <div className="flex justify-between text-xs text-muted-foreground font-semibold">
          <div>
            Showing {logs.length.toLocaleString()} of {totalCount.toLocaleString()} total entries
          </div>
          <div>
            {selectedFiles.length > 0 && selectedFiles[0] !== 'ALL' ? `File: ${selectedFiles[0]}` : `Merged from ${availableFiles.length} files`}
          </div>
        </div>
      </Card>
      </TabsContent>
      </Tabs>
    </div>
  )
}
