'use client'

import { useState, useEffect, useImperativeHandle, forwardRef } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'
import { TrendingUp, Loader2 } from 'lucide-react'

export interface AIConfigPanelRef {
  save: () => Promise<void>
  reset: () => void
}

interface AIConfig {
  enablePositionSizing: boolean
  baseRiskPercent: number
  minLotSize: number
  maxLotSize: number
  volatilityMultiplier: number
}

interface AIConfigPanelProps {
  onDirtyChange?: (dirty: boolean) => void
}

const AIConfigPanel = forwardRef<AIConfigPanelRef, AIConfigPanelProps>(function AIConfigPanel(
  { onDirtyChange },
  ref
) {
  const { toast } = useToast()
  const [config, setConfig] = useState<AIConfig | null>(null)
  const [savedConfig, setSavedConfig] = useState<AIConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [reloading, setReloading] = useState(false)

  useEffect(() => {
    fetchConfig()
  }, [])

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        fetchConfig()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [])

  useEffect(() => {
    if (!config || !savedConfig) return
    const dirty = JSON.stringify(config) !== JSON.stringify(savedConfig)
    onDirtyChange?.(dirty)
  }, [config, savedConfig])

  const fetchConfig = async () => {
    setReloading(true)
    try {
      const timestamp = Date.now()
      const res = await fetch(`/api/ai-config?_t=${timestamp}`)
      const data = await res.json()
      const slice: AIConfig = {
        enablePositionSizing: data.enablePositionSizing,
        baseRiskPercent: data.baseRiskPercent,
        minLotSize: data.minLotSize,
        maxLotSize: data.maxLotSize,
        volatilityMultiplier: data.volatilityMultiplier,
      }
      setConfig(slice)
      setSavedConfig(slice)
      onDirtyChange?.(false)
    } catch (error) {
      toast({
        title: 'Error',
        description: 'Failed to load AI configuration',
        variant: 'destructive'
      })
    } finally {
      setLoading(false)
      setReloading(false)
    }
  }

  const saveConfig = async () => {
    if (!config) return
    const res = await fetch('/api/ai-config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config)
    })
    if (!res.ok) throw new Error('Failed to save AI configuration')
    setSavedConfig(config)
    onDirtyChange?.(false)
  }

  useImperativeHandle(ref, () => ({
    save: saveConfig,
    reset: () => {
      if (savedConfig) {
        setConfig(savedConfig)
        onDirtyChange?.(false)
      }
    },
  }))

  const updateConfig = (patch: Partial<AIConfig>) => {
    setConfig(prev => prev ? { ...prev, ...patch } : prev)
  }

  if (loading || !config) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-green-500" />
            Position Sizing
          </CardTitle>
          <CardDescription>
            AI calculates optimal lot sizes based on account risk and market conditions
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <Label htmlFor="position-sizing">Enable Position Sizing</Label>
            <Switch
              id="position-sizing"
              checked={config.enablePositionSizing}
              onCheckedChange={(checked) => updateConfig({ enablePositionSizing: checked })}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="base-risk">Base Risk %</Label>
              <Input
                id="base-risk"
                type="number"
                step="0.5"
                min="0"
                max="10"
                value={config.baseRiskPercent}
                onChange={(e) => updateConfig({ baseRiskPercent: parseFloat(e.target.value) || 0 })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="volatility-multiplier">Volatility Multiplier</Label>
              <Input
                id="volatility-multiplier"
                type="number"
                step="0.1"
                min="0"
                max="3"
                value={config.volatilityMultiplier}
                onChange={(e) => updateConfig({ volatilityMultiplier: parseFloat(e.target.value) || 0 })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="min-lot">Min Lot Size</Label>
              <Input
                id="min-lot"
                type="number"
                step="0.01"
                min="0.01"
                value={config.minLotSize}
                onChange={(e) => updateConfig({ minLotSize: parseFloat(e.target.value) || 0.01 })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="max-lot">Max Lot Size</Label>
              <Input
                id="max-lot"
                type="number"
                step="0.01"
                min="0.01"
                value={config.maxLotSize}
                onChange={(e) => updateConfig({ maxLotSize: parseFloat(e.target.value) || 1 })}
              />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
})

export default AIConfigPanel
