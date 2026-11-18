'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { RefreshCw, Eye, AlertTriangle, Search, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ModelInfo {
  id: string
  context: string
  inputCost: number | null
  outputCost: number | null
  vision: boolean
}

interface ModelSelectProps {
  provider: string
  value: string
  onChange: (value: string) => void
  hasChanged?: boolean
}

function formatCost(n: number | null): string {
  if (n === null) return '?'
  if (n < 0.1) return `$${n.toFixed(3)}`
  return `$${n.toFixed(2)}`
}

function ModelLabel({ model }: { model: ModelInfo }) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1.5">
        <span className="font-semibold text-xs">{model.id}</span>
        {model.vision && <Eye className="h-2.5 w-2.5 text-primary/80 shrink-0" />}
      </div>
      {(model.context !== '?' || model.inputCost !== null) && (
        <span className="text-[10px] text-muted-foreground font-medium">
          {model.context} ctx · {formatCost(model.inputCost)}/{formatCost(model.outputCost)} /1M
        </span>
      )}
    </div>
  )
}

export default function ModelSelect({ provider, value, onChange, hasChanged }: ModelSelectProps) {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fetched, setFetched] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const [manualEntry, setManualEntry] = useState(false)

  const fetchModels = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/ai/models?provider=${provider}`)
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? 'Failed to load')
      setModels(data.models ?? [])
      setFetched(true)
    } catch (err: any) {
      setError(err.message ?? 'Failed to load models')
      setFetched(true)
    } finally {
      setLoading(false)
    }
  }, [provider])

  useEffect(() => {
    fetchModels()
  }, [provider, fetchModels])

  // When fetch failed or returned no models → show plain text input so user
  // can still type any model ID manually (provider may have no public API).
  const noModels = fetched && models.length === 0
  if (error || noModels || manualEntry) {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-1.5">
          <Input
            value={value || ''}
            onChange={(e) => onChange(e.target.value)}
            placeholder="Enter model ID…"
            className={cn('w-[220px] h-9 text-xs font-semibold', hasChanged && 'border-orange-400 bg-orange-50')}
          />
          {!error && !noModels && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 shrink-0 text-muted-foreground hover:text-foreground"
              onClick={() => setManualEntry(false)}
              title="Use dropdown"
            >
              <RefreshCw className="h-3 w-3" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0 text-muted-foreground hover:text-foreground"
            onClick={fetchModels}
            disabled={loading}
            title="Retry fetching models"
          >
            <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} />
          </Button>
        </div>
        {error && (
          <div className="flex items-center gap-1 text-[10px] text-gold font-medium">
            <AlertTriangle className="h-2.5 w-2.5 shrink-0" />
            <span>Can't fetch models — type ID manually. ({error})</span>
          </div>
        )}
        {noModels && !manualEntry && (
          <div className="flex items-center gap-1 text-[10px] text-gold font-medium">
            <AlertTriangle className="h-2.5 w-2.5 shrink-0" />
            <span>No models available — type ID manually.</span>
          </div>
        )}
      </div>
    )
  }

  // If current value not in fetched list, still show it as an option
  const currentInList = models.some(m => m.id === value)
  const displayModels =
    !currentInList && value
      ? [{ id: value, context: '?', inputCost: null, outputCost: null, vision: false }, ...models]
      : models

  // Filter models based on search query
  const filteredModels = displayModels.filter(model =>
    model.id.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const handleClearSearch = () => {
    setSearchQuery('')
  }

  return (
    <div className="flex items-center gap-1.5">
      <Select 
        value={value || ''} 
        onValueChange={(v) => {
          onChange(v)
          setSearchQuery('')
        }}
        onOpenChange={setIsOpen}
      >
        <SelectTrigger
          className={cn(
            'w-[220px] h-9 text-xs font-semibold',
            hasChanged && 'border-orange-400 bg-orange-50',
          )}
        >
          {loading ? (
            <span className="text-[10px] text-muted-foreground">Loading models…</span>
          ) : (
            <SelectValue placeholder="Select model" />
          )}
        </SelectTrigger>
        <SelectContent className="max-h-80">
          {/* Search input inside dropdown */}
          <div className="p-2 border-b">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
              <Input
                placeholder="Search models..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-8 h-7 text-xs"
                onClick={(e) => e.stopPropagation()}
              />
              {searchQuery && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    handleClearSearch()
                  }}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          </div>
          
          {/* Filtered models */}
          <div className="max-h-60 overflow-y-auto">
            {filteredModels.length === 0 ? (
              <div className="py-4 flex flex-col items-center gap-2">
                <span className="text-xs text-muted-foreground">No models found</span>
                <Button
                  variant="outline"
                  size="sm"
                  className="text-xs h-7"
                  onClick={() => {
                    setManualEntry(true)
                    setIsOpen(false)
                  }}
                >
                  Enter model ID manually
                </Button>
              </div>
            ) : (
              filteredModels.map(model => (
                <SelectItem key={model.id} value={model.id} className="text-xs py-2">
                  <ModelLabel model={model} />
                </SelectItem>
              ))
            )}
          </div>
        </SelectContent>
      </Select>

      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7 shrink-0 text-muted-foreground hover:text-foreground"
        onClick={fetchModels}
        disabled={loading}
        title="Refresh model list"
      >
        <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} />
      </Button>
    </div>
  )
}
