'use client'

import { useState, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import MobilePageHeader from '@/components/MobilePageHeader'
import { Settings as SettingsIcon, AlertTriangle, Trash2, Wrench, Bell, BellOff, Bug, Link2, Save, Share2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useToast } from '@/hooks/use-toast'
import {
  DEFAULT_NEWS_SHARE_CONFIG,
  parseNewsShareConfig,
  type NewsShareConfig,
} from '@/lib/types/newsShare'

interface UserSettings {
  notificationsEnabled: boolean
  tradeNotificationsEnabled: boolean
  systemNotificationsEnabled: boolean
  errorNotificationsEnabled: boolean
  debugModeEnabled: boolean
  consoleLogsEnabled: boolean
  disabledConnections: string
}

// Names match the cards on the Connections page (/api/connections).
const availableConnections = [
  'Bot Engine',
  'MetaAPI',
  'MT5 REST API',
  'Telegram',
  'Trade Copier',
  'News Monitor',
  'Notifications',
  'Database',
  'Redis',
]

export default function SettingsPage() {
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [isDeleting, setIsDeleting] = useState(false)
  const [isFixing, setIsFixing] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const router = useRouter()
  const { toast } = useToast()

  const [settings, setSettings] = useState<UserSettings>({
    notificationsEnabled: true,
    tradeNotificationsEnabled: true,
    systemNotificationsEnabled: true,
    errorNotificationsEnabled: true,
    debugModeEnabled: false,
    consoleLogsEnabled: false,
    disabledConnections: '[]',
  })

  const [disabledConnectionsList, setDisabledConnectionsList] = useState<string[]>([])
  const [shareConfig, setShareConfig] = useState<NewsShareConfig>(DEFAULT_NEWS_SHARE_CONFIG)

  useEffect(() => {
    fetchSettings()
  }, [])

  const fetchSettings = async () => {
    try {
      setLoading(true)
      const response = await fetch('/api/user-settings')
      if (response.ok) {
        const data = await response.json()
        setSettings({
          notificationsEnabled: data.notificationsEnabled ?? true,
          tradeNotificationsEnabled: data.tradeNotificationsEnabled ?? true,
          systemNotificationsEnabled: data.systemNotificationsEnabled ?? true,
          errorNotificationsEnabled: data.errorNotificationsEnabled ?? true,
          debugModeEnabled: data.debugModeEnabled ?? false,
          consoleLogsEnabled: data.consoleLogsEnabled ?? false,
          disabledConnections: data.disabledConnections ?? '[]',
        })
        try {
          const parsed = JSON.parse(data.disabledConnections || '[]')
          setDisabledConnectionsList(Array.isArray(parsed) ? parsed : [])
        } catch {
          setDisabledConnectionsList([])
        }
        setShareConfig(parseNewsShareConfig(data.newsShareConfig))
      }
    } catch (err) {
      console.error('Failed to fetch settings:', err)
    } finally {
      setLoading(false)
    }
  }

  const saveSettings = async () => {
    try {
      setSaving(true)
      const response = await fetch('/api/user-settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...settings,
          disabledConnections: JSON.stringify(disabledConnectionsList),
          newsShareConfig: JSON.stringify(shareConfig),
        }),
      })

      if (response.ok) {
        toast({
          title: 'Settings saved',
          description: 'Your preferences have been updated successfully.',
        })
      } else {
        throw new Error('Failed to save settings')
      }
    } catch (err) {
      toast({
        title: 'Error',
        description: err instanceof Error ? err.message : 'Failed to save settings',
        variant: 'destructive',
      })
    } finally {
      setSaving(false)
    }
  }

  const updateShareConfig = <K extends keyof NewsShareConfig>(key: K, value: NewsShareConfig[K]) => {
    setShareConfig(prev => ({ ...prev, [key]: value }))
  }

  const toggleConnection = (connectionName: string) => {
    setDisabledConnectionsList(prev => {
      if (prev.includes(connectionName)) {
        return prev.filter(c => c !== connectionName)
      } else {
        return [...prev, connectionName]
      }
    })
  }

  const handleDelete = async () => {
    if (confirmText !== 'DELETE') {
      setError('Please type DELETE to confirm')
      return
    }

    setIsDeleting(true)
    setError('')
    setSuccess('')

    try {
      const response = await fetch('/api/cleanup', {
        method: 'POST',
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.error || 'Failed to cleanup database')
      }

      const result = await response.json()
      setSuccess(`Successfully deleted: ${result.deletedSignals} signals, ${result.deletedTrades} trades, ${result.deletedActions} actions, ${result.deletedMessages} messages`)
      setConfirmText('')
      setIsDialogOpen(false)
      
      // Refresh the page after 2 seconds
      setTimeout(() => {
        router.push('/')
      }, 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setIsDeleting(false)
    }
  }

  const handleFixDatabase = async () => {
    setIsFixing(true)
    setError('')
    setSuccess('')

    try {
      const response = await fetch('/api/fix-database', {
        method: 'POST',
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.error || 'Failed to fix database')
      }

      const result = await response.json()
      setSuccess(`Database fixed! ${result.signalsFixed} signals corrected, ${result.repliesLinked} replies linked, ${result.repliesDeleted} orphaned replies removed`)
      
      // Refresh the page after 2 seconds
      setTimeout(() => {
        router.refresh()
      }, 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setIsFixing(false)
    }
  }


  return (
    <div className="flex min-h-full flex-col">
      <MobilePageHeader 
        title="Settings" 
        subtitle="System Configuration"
        hidden
        icon={<SettingsIcon className="h-5 w-5" />}
      />
      
      <header className="hidden md:flex sticky top-0 z-40 w-full tech-header">
        <div className="max-w-[1800px] w-full mx-auto flex h-14 items-center px-6 gap-3">
          <div className="p-1.5 rounded-lg bg-primary/10 border border-primary/20">
            <SettingsIcon className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col">
            <h1 className="text-sm font-bold text-foreground leading-none">Settings</h1>
            <p className="text-[10px] text-[#6b7288] font-bold uppercase tracking-wider mt-1">System Configuration</p>
          </div>
        </div>
      </header>

      <div className="flex-1 px-3 md:px-4 py-3 md:py-4">
        <div className="max-w-4xl mx-auto space-y-4">
          {/* Notification Settings */}
          <Card className="border shadow-sm bg-card">
            <CardHeader className="pb-3 pt-4 px-4 border-b">
              <CardTitle className="text-sm flex items-center gap-2 font-bold">
                <Bell className="h-4 w-4" />
                Notification Settings
              </CardTitle>
              <CardDescription className="text-xs font-semibold">
                Control which notifications you receive
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 px-4 pb-4 pt-4">
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="notifications" className="text-sm font-semibold">All Notifications</Label>
                  <p className="text-xs text-muted-foreground">Enable or disable all notifications</p>
                </div>
                <Switch
                  id="notifications"
                  checked={settings.notificationsEnabled}
                  onCheckedChange={(checked) => setSettings({ ...settings, notificationsEnabled: checked })}
                />
              </div>

              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="trade-notifications" className="text-sm font-semibold">Trade Notifications</Label>
                  <p className="text-xs text-muted-foreground">Notifications for trade executions and updates</p>
                </div>
                <Switch
                  id="trade-notifications"
                  checked={settings.tradeNotificationsEnabled}
                  onCheckedChange={(checked) => setSettings({ ...settings, tradeNotificationsEnabled: checked })}
                  disabled={!settings.notificationsEnabled}
                />
              </div>

              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="system-notifications" className="text-sm font-semibold">System Notifications</Label>
                  <p className="text-xs text-muted-foreground">System status and health updates</p>
                </div>
                <Switch
                  id="system-notifications"
                  checked={settings.systemNotificationsEnabled}
                  onCheckedChange={(checked) => setSettings({ ...settings, systemNotificationsEnabled: checked })}
                  disabled={!settings.notificationsEnabled}
                />
              </div>

              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="error-notifications" className="text-sm font-semibold">Error Notifications</Label>
                  <p className="text-xs text-muted-foreground">Critical errors and warnings</p>
                </div>
                <Switch
                  id="error-notifications"
                  checked={settings.errorNotificationsEnabled}
                  onCheckedChange={(checked) => setSettings({ ...settings, errorNotificationsEnabled: checked })}
                  disabled={!settings.notificationsEnabled}
                />
              </div>
            </CardContent>
          </Card>

          {/* Debug Settings */}
          <Card className="border shadow-sm bg-card">
            <CardHeader className="pb-3 pt-4 px-4 border-b">
              <CardTitle className="text-sm flex items-center gap-2 font-bold">
                <Bug className="h-4 w-4" />
                Debug & Developer Settings
              </CardTitle>
              <CardDescription className="text-xs font-semibold">
                Advanced settings for debugging and development
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 px-4 pb-4 pt-4">
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="debug-mode" className="text-sm font-semibold">Debug Mode</Label>
                  <p className="text-xs text-muted-foreground">Show detailed debug information in the UI</p>
                </div>
                <Switch
                  id="debug-mode"
                  checked={settings.debugModeEnabled}
                  onCheckedChange={(checked) => setSettings({ ...settings, debugModeEnabled: checked })}
                />
              </div>

              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="console-logs" className="text-sm font-semibold">Console Logs</Label>
                  <p className="text-xs text-muted-foreground">Enable verbose console logging</p>
                </div>
                <Switch
                  id="console-logs"
                  checked={settings.consoleLogsEnabled}
                  onCheckedChange={(checked) => setSettings({ ...settings, consoleLogsEnabled: checked })}
                />
              </div>
            </CardContent>
          </Card>

          {/* Connection Management */}
          <Card className="border shadow-sm bg-card">
            <CardHeader className="pb-3 pt-4 px-4 border-b">
              <CardTitle className="text-sm flex items-center gap-2 font-bold">
                <Link2 className="h-4 w-4" />
                Connection Management
              </CardTitle>
              <CardDescription className="text-xs font-semibold">
                Manually disable connections to hide them from the dashboard
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 px-4 pb-4 pt-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {availableConnections.map((connection) => {
                  const isDisabled = disabledConnectionsList.includes(connection)
                  return (
                    <div
                      key={connection}
                      className={`flex items-center justify-between p-3 rounded-lg border transition-colors ${
                        isDisabled ? 'bg-muted/50 border-border' : 'bg-card border-border'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {isDisabled ? (
                          <BellOff className="h-4 w-4 text-muted-foreground/70" />
                        ) : (
                          <Link2 className="h-4 w-4 text-primary" />
                        )}
                        <span className={`text-sm font-semibold ${
                          isDisabled ? 'text-muted-foreground' : 'text-foreground'
                        }`}>
                          {connection}
                        </span>
                      </div>
                      <Switch
                        checked={!isDisabled}
                        onCheckedChange={() => toggleConnection(connection)}
                      />
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>

          {/* News Share Branding */}
          <Card className="border shadow-sm bg-card">
            <CardHeader className="pb-3 pt-4 px-4 border-b">
              <CardTitle className="text-sm flex items-center gap-2 font-bold">
                <Share2 className="h-4 w-4" />
                News Share Format
              </CardTitle>
              <CardDescription className="text-xs font-semibold">
                Branding &amp; layout for the calendar &quot;Share&quot; button (text + image)
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 px-4 pb-4 pt-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <Label htmlFor="brand-name" className="text-sm font-semibold">Brand / Channel Name</Label>
                  <Input
                    id="brand-name"
                    value={shareConfig.brandName}
                    onChange={(e) => updateShareConfig('brandName', e.target.value)}
                    placeholder="e.g. NEXAL"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="header-subtitle" className="text-sm font-semibold">Header Subtitle</Label>
                  <Input
                    id="header-subtitle"
                    value={shareConfig.headerSubtitle}
                    onChange={(e) => updateShareConfig('headerSubtitle', e.target.value)}
                    placeholder="e.g. Daily Economic Calendar"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="share-footer" className="text-sm font-semibold">Footer</Label>
                <Textarea
                  id="share-footer"
                  value={shareConfig.footer}
                  onChange={(e) => updateShareConfig('footer', e.target.value)}
                  placeholder="e.g. t.me/yourchannel · Not financial advice"
                  rows={2}
                  className="resize-none text-sm"
                />
              </div>

              <div className="flex items-center gap-4 flex-wrap">
                <div className="flex items-center gap-2">
                  <Label htmlFor="accent-color" className="text-sm font-semibold">Image Accent</Label>
                  <input
                    id="accent-color"
                    type="color"
                    value={shareConfig.accentColor}
                    onChange={(e) => updateShareConfig('accentColor', e.target.value)}
                    className="h-8 w-12 rounded border border-border bg-transparent cursor-pointer p-0.5"
                    aria-label="Image accent colour"
                  />
                  <span className="text-xs font-mono text-muted-foreground">{shareConfig.accentColor}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Label htmlFor="max-events" className="text-sm font-semibold">Max events</Label>
                  <Input
                    id="max-events"
                    type="number"
                    min={0}
                    value={shareConfig.maxEvents}
                    onChange={(e) => updateShareConfig('maxEvents', Math.max(0, parseInt(e.target.value) || 0))}
                    className="w-20"
                  />
                  <span className="text-xs text-muted-foreground">(0 = all)</span>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3 pt-1 border-t border-border/50">
                {([
                  ['showTime', 'Show event time'],
                  ['showFlag', 'Show currency flag'],
                  ['showForecastPrevious', 'Show forecast / previous'],
                  ['showActual', 'Show actual value'],
                  ['groupByDate', 'Group under date headings'],
                  ['showTimezoneNote', 'Append timezone note'],
                ] as [keyof NewsShareConfig, string][]).map(([key, label]) => (
                  <div key={key} className="flex items-center justify-between">
                    <Label htmlFor={`share-${key}`} className="text-sm font-medium">{label}</Label>
                    <Switch
                      id={`share-${key}`}
                      checked={shareConfig[key] as boolean}
                      onCheckedChange={(checked) => updateShareConfig(key, checked as never)}
                    />
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Save Button */}
          <div className="flex justify-end">
            <Button onClick={saveSettings} disabled={saving || loading} className="font-semibold">
              <Save className="h-4 w-4 mr-2" />
              {saving ? 'Saving...' : 'Save Settings'}
            </Button>
          </div>

          {/* Danger Zone */}
          <Card className="border-destructive/40 bg-card shadow-sm">
            <CardHeader className="pb-3 pt-4 px-4 border-b bg-destructive/10/50">
              <CardTitle className="text-sm text-destructive flex items-center gap-2 font-bold">
                <AlertTriangle className="h-4 w-4" />
                Danger Zone
              </CardTitle>
              <CardDescription className="text-xs font-semibold text-destructive">
                Irreversible actions that affect your data
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 px-4 pb-4 pt-4">
              <div className="border border-blue-300 rounded-lg p-4 space-y-2.5 bg-primary/10">
                <div>
                  <h3 className="text-sm font-bold text-primary">Fix Database Issues</h3>
                  <p className="text-xs text-primary mt-1 font-medium">
                    Fix channel ID mismatches, link unlinked replies, and remove orphaned replies.
                  </p>
                </div>
                <Button variant="outline" onClick={handleFixDatabase} disabled={isFixing} size="sm" className="border-blue-400 hover:bg-primary/10 font-semibold">
                  <Wrench className="h-3.5 w-3.5 mr-1.5" />
                  {isFixing ? 'Fixing...' : 'Fix Database'}
                </Button>
              </div>

              <div className="border border-border rounded-lg p-4 space-y-2.5 bg-card">
                <div>
                  <h3 className="text-sm font-bold text-foreground">Clear All Database Records</h3>
                  <p className="text-xs text-muted-foreground mt-1 font-medium">
                    Delete all signals, trades, trade actions, and message mappings. Trading sessions will be preserved.
                  </p>
                </div>
                <Button variant="destructive" onClick={() => setIsDialogOpen(true)} size="sm" className="font-semibold">
                  <Trash2 className="h-3.5 w-3.5 mr-1.5" />
                  Clear Database
                </Button>
              </div>

              {error && (
                <div className="border border-destructive/40 rounded-lg p-3 text-xs text-destructive bg-destructive/10 font-semibold">
                  {error}
                </div>
              )}

              {success && (
                <div className="border border-success/40 rounded-lg p-3 text-xs text-success bg-success/10 font-semibold">
                  {success}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Confirmation Dialog */}
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="text-destructive dark:text-red-400 flex items-center gap-2">
              <AlertTriangle className="h-5 w-5" />
              Confirm Database Cleanup
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3 pt-2">
            <p className="font-semibold text-sm text-muted-foreground">This action will permanently delete:</p>
            <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
              <li>All trading signals</li>
              <li>All trades and positions</li>
              <li>All trade actions and modifications</li>
              <li>All message mappings</li>
            </ul>
            <p className="text-destructive dark:text-red-400 font-semibold text-sm">
              This action cannot be undone!
            </p>
            <p className="text-sm text-muted-foreground mt-4">
              To confirm, type <strong>DELETE</strong> in the box below:
            </p>
          </div>
          <div className="py-4">
            <Input
              value={confirmText}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setConfirmText(e.target.value)}
              placeholder="Type DELETE to confirm"
              className="font-mono"
              disabled={isDeleting}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setIsDialogOpen(false)
                setConfirmText('')
                setError('')
              }}
              disabled={isDeleting}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={confirmText !== 'DELETE' || isDeleting}
            >
              {isDeleting ? 'Deleting...' : 'Delete Everything'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
