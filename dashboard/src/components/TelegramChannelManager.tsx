'use client'

import React, { useState, useEffect } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { useToast } from '@/hooks/use-toast'
import {
  Search,
  RefreshCw,
  Loader2,
  Radio,
  Users,
  Plus,
  Trash2,
  CheckCircle2,
  Signal,
  Hash,
  Sparkles,
} from 'lucide-react'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001'

// ─── Types ──────────────────────────────────────────────────────────────────

interface Channel {
  id?: number
  channel_id: string
  channel_title: string
  channel_username?: string
  access_hash?: string
  is_broadcast: boolean
  is_megagroup: boolean
  participants_count?: number
  photo_url?: string
  is_active?: boolean
  added_at?: string
  last_updated?: string
}

interface TelegramChannel {
  title: string
  username?: string
  id: string
  access_hash?: string
  megagroup: boolean
  broadcast: boolean
  participants_count?: number
}

interface ChannelData {
  statistics: {
    total_dialogs: number
    channels: number
    supergroups: number
    groups: number
    private_chats: number
  }
  channels: TelegramChannel[]
  supergroups: TelegramChannel[]
  groups: TelegramChannel[]
  private_chats: TelegramChannel[]
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function TelegramChannelManager() {
  const [allChannels, setAllChannels] = useState<ChannelData | null>(null)
  const [monitoredChannels, setMonitoredChannels] = useState<Channel[]>([])
  const [loading, setLoading] = useState(false)
  const [fetchingAll, setFetchingAll] = useState(false)
  const [activeTab, setActiveTab] = useState<'monitored' | 'all'>('monitored')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedChannel, setSelectedChannel] = useState<TelegramChannel | null>(null)
  const [showAddDialog, setShowAddDialog] = useState(false)
  const { toast } = useToast()

  // ── Fetch monitored channels ─────────────────────────────────────────────

  const fetchMonitoredChannels = async () => {
    setLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/telegram/channels/monitored`)
      const data = await response.json()
      if (data.success) {
        setMonitoredChannels(data.data)
      } else {
        throw new Error(data.error || 'Failed to fetch monitored channels')
      }
    } catch (error) {
      console.error('Error fetching monitored channels:', error)
      toast({ title: 'Error', description: 'Failed to fetch monitored channels', variant: 'destructive' })
    } finally {
      setLoading(false)
    }
  }

  // ── Fetch all channels from cache ────────────────────────────────────────

  const fetchAllChannels = async () => {
    setFetchingAll(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/telegram/channels/all`)
      const data = await response.json()
      if (data.success) {
        setAllChannels(data.data)
        toast({ title: 'Channels loaded', description: `${data.data.statistics.total_dialogs} dialogs from cache` })
      } else {
        throw new Error(data.error || 'Failed to fetch channels')
      }
    } catch (error) {
      console.error('Error fetching all channels:', error)
      toast({ title: 'Error', description: 'Failed to fetch channels from Telegram', variant: 'destructive' })
    } finally {
      setFetchingAll(false)
    }
  }

  // ── Force-refresh cache from Telegram ─────────────────────────────────────

  const refreshAllChannels = async () => {
    setFetchingAll(true)
    try {
      const response = await fetch(`${API_BASE_URL}/api/telegram/channels/refresh`, { method: 'POST' })
      const data = await response.json()
      if (data.success) {
        setAllChannels(data.data)
        toast({ title: 'Refreshed', description: `${data.data.statistics.total_dialogs} dialogs from Telegram` })
      } else {
        throw new Error(data.error || 'Failed to refresh channels')
      }
    } catch (error) {
      console.error('Error refreshing channels:', error)
      toast({ title: 'Error', description: 'Failed to refresh from Telegram', variant: 'destructive' })
    } finally {
      setFetchingAll(false)
    }
  }

  // ── Add / Remove / Toggle ─────────────────────────────────────────────────

  const addChannelToMonitoring = async (channel: TelegramChannel) => {
    try {
      let photoUrl: string | undefined
      try {
        const photoResponse = await fetch(`${API_BASE_URL}/api/telegram/channels/${channel.id}/photo`)
        const photoData = await photoResponse.json()
        if (photoData.success && photoData.photo) photoUrl = `data:image/jpeg;base64,${photoData.photo}`
      } catch (e) { console.warn('Could not fetch channel photo:', e) }

      const response = await fetch(`${API_BASE_URL}/api/telegram/channels/monitored`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel_id: channel.id, channel_title: channel.title,
          channel_username: channel.username, access_hash: channel.access_hash,
          is_broadcast: channel.broadcast, is_megagroup: channel.megagroup,
          participants_count: channel.participants_count, photo_url: photoUrl,
        }),
      })
      const data = await response.json()
      if (data.success) {
        toast({ title: 'Added', description: `${channel.title} is now monitored` })
        fetchMonitoredChannels()
        setShowAddDialog(false)
      } else {
        throw new Error(data.error || 'Failed to add channel')
      }
    } catch (error) {
      console.error('Error adding channel:', error)
      toast({ title: 'Error', description: 'Failed to add channel', variant: 'destructive' })
    }
  }

  const removeChannelFromMonitoring = async (channelId: string, channelTitle: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/telegram/channels/monitored/${channelId}`, { method: 'DELETE' })
      const data = await response.json()
      if (data.success) {
        toast({ title: 'Removed', description: `${channelTitle} unmonitored` })
        fetchMonitoredChannels()
      } else throw new Error(data.error || 'Failed to remove channel')
    } catch (error) {
      console.error('Error removing channel:', error)
      toast({ title: 'Error', description: 'Failed to remove channel', variant: 'destructive' })
    }
  }

  const toggleChannelStatus = async (channelId: string, currentStatus: boolean, channelTitle: string) => {
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/telegram/channels/monitored/${channelId}/status`,
        { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: !currentStatus }) }
      )
      const data = await response.json()
      if (data.success) {
        toast({ title: 'Updated', description: `${channelTitle} ${!currentStatus ? 'enabled' : 'paused'}` })
        fetchMonitoredChannels()
      } else throw new Error(data.error || 'Failed to toggle status')
    } catch (error) {
      console.error('Error toggling status:', error)
      toast({ title: 'Error', description: 'Failed to toggle channel status', variant: 'destructive' })
    }
  }

  useEffect(() => { fetchMonitoredChannels() }, [])

  const isChannelMonitored = (channelId: string) =>
    monitoredChannels.some((ch) => ch.channel_id === channelId)

  const filterChannels = (channels: TelegramChannel[]) => {
    if (!searchQuery) return channels
    const query = searchQuery.toLowerCase()
    return channels.filter(
      (ch) => ch.title.toLowerCase().includes(query) || (ch.username && ch.username.toLowerCase().includes(query))
    )
  }

  // ── Stat card config ─────────────────────────────────────────────────────

  const statCards = allChannels
    ? [
        { label: 'Total', value: allChannels.statistics.total_dialogs, tone: 'muted' as const },
        { label: 'Channels', value: allChannels.statistics.channels, tone: 'blue' as const },
        { label: 'Supergroups', value: allChannels.statistics.supergroups, tone: 'emerald' as const },
        { label: 'Groups', value: allChannels.statistics.groups, tone: 'violet' as const },
        { label: 'Private', value: allChannels.statistics.private_chats, tone: 'amber' as const },
      ]
    : []

  const statToneStyles: Record<string, { text: string; bg: string }> = {
    muted:  { text: 'text-foreground',                bg: 'bg-muted/40' },
    blue:   { text: 'text-blue-600 dark:text-blue-400',     bg: 'bg-blue-500/20 dark:bg-blue-500/15' },
    emerald:{ text: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-500/20 dark:bg-emerald-500/15' },
    violet: { text: 'text-violet-600 dark:text-violet-400',   bg: 'bg-violet-500/20 dark:bg-violet-500/15' },
    amber:  { text: 'text-amber-600 dark:text-amber-400',     bg: 'bg-amber-500/20 dark:bg-amber-500/15' },
  }

  // ── Render: Available channel card ──────────────────────────────────────

  const renderChannelCard = (channel: TelegramChannel, isMonitored: boolean) => (
    <div
      key={channel.id}
      className="group rounded-xl border border-border/50 bg-card/70 backdrop-blur-sm
        hover:border-primary/30 hover:shadow-md dark:hover:shadow-primary/5
        transition-all duration-200 ease-out"
    >
      <div className="p-4">
        <div className="flex items-start gap-3">
          <div className="w-11 h-11 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-600/20
            dark:from-blue-500/30 dark:to-purple-600/30
            flex items-center justify-center text-lg shrink-0 ring-2 ring-border/30">
            {channel.broadcast ? '📢' : '💬'}
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-sm truncate text-foreground">{channel.title}</h3>
            {channel.username && <p className="text-xs text-muted-foreground/60">@{channel.username}</p>}
            <div className="flex items-center gap-1.5 mt-1.5">
              {channel.participants_count != null && channel.participants_count > 0 && (
                <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground/50 bg-muted/40 px-1.5 py-0.5 rounded-full">
                  <Users className="w-2.5 h-2.5" />{channel.participants_count.toLocaleString()}
                </span>
              )}
              {channel.broadcast && (
                <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground/50 bg-muted/40 px-1.5 py-0.5 rounded-full">
                  <Radio className="w-2.5 h-2.5" />Channel
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="mt-3">
          {isMonitored ? (
            <Button variant="secondary" size="sm" className="w-full h-8 rounded-lg" disabled>
              <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" />Already Monitored
            </Button>
          ) : (
            <Button variant="default" size="sm" className="w-full h-8 rounded-lg shadow-sm"
              onClick={() => { setSelectedChannel(channel); setShowAddDialog(true) }}>
              <Plus className="w-3.5 h-3.5 mr-1.5" />Add to Monitoring
            </Button>
          )}
        </div>
      </div>
    </div>
  )

  // ── Render: Monitored channel card ──────────────────────────────────────

  const renderMonitoredChannelCard = (channel: Channel) => (
    <div
      key={channel.id}
      className={`relative rounded-xl border backdrop-blur-sm transition-all duration-200 ease-out
        ${channel.is_active
          ? 'border-emerald-200/60 dark:border-emerald-800/50 bg-card/80 hover:shadow-md dark:hover:shadow-emerald-950/20'
          : 'border-border/40 bg-card/50 hover:border-border/60'
        }`}
    >
      {channel.is_active && (
        <div className="absolute top-3 right-3 flex items-center gap-1.5">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
          </span>
        </div>
      )}
      <div className="p-4">
        <div className="flex items-start gap-3">
          {channel.photo_url ? (
            <img src={channel.photo_url} alt={channel.channel_title}
              className="w-11 h-11 rounded-full object-cover shrink-0 ring-2 ring-border/30" />
          ) : (
            <div className={`w-11 h-11 rounded-full flex items-center justify-center text-lg shrink-0 ring-2
              ${channel.is_active
                ? 'bg-emerald-100 dark:bg-emerald-900/40 ring-emerald-300/40 dark:ring-emerald-700/40'
                : 'bg-muted ring-border/20'
              }`}>
              {channel.is_broadcast ? '📢' : '💬'}
            </div>
          )}
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-sm truncate text-foreground pr-10">{channel.channel_title}</h3>
            {channel.channel_username && <p className="text-xs text-muted-foreground/60">@{channel.channel_username}</p>}
            <div className="flex items-center gap-1.5 mt-1.5">
              {channel.participants_count != null && channel.participants_count > 0 && (
                <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground/50 bg-muted/40 px-1.5 py-0.5 rounded-full">
                  <Users className="w-2.5 h-2.5" />{channel.participants_count.toLocaleString()}
                </span>
              )}
              <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground/40 bg-muted/30 px-1.5 py-0.5 rounded-full font-mono">
                <Hash className="w-2.5 h-2.5" />{channel.channel_id}
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 mt-3 pt-3 border-t border-border/40">
          <div className="flex items-center gap-2 flex-1">
            <Switch
              checked={channel.is_active || false}
              onCheckedChange={() => toggleChannelStatus(channel.channel_id, channel.is_active || false, channel.channel_title)}
              className="data-[state=checked]:bg-emerald-500 dark:data-[state=checked]:bg-emerald-600"
            />
            <span className="text-[11px] text-muted-foreground/60">
              {channel.is_active ? 'Monitoring' : 'Paused'}
            </span>
          </div>
          <Button variant="ghost" size="sm"
            className="h-7 w-7 p-0 rounded-full text-muted-foreground/40 hover:text-red-500 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40"
            onClick={() => removeChannelFromMonitoring(channel.channel_id, channel.channel_title)}
            title="Remove from monitoring">
            <Trash2 className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>
    </div>
  )

  // ── Main Render ──────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">Signal Channels</h2>
          <p className="text-sm text-muted-foreground/70 mt-0.5">
            Channels the bot monitors for incoming trading signals
          </p>
        </div>
        <Button onClick={fetchMonitoredChannels} variant="outline" size="sm"
          className="h-9 rounded-xl gap-1.5" disabled={loading}>
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          Refresh
        </Button>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as 'monitored' | 'all')}>
        <TabsList className="grid w-full grid-cols-2 h-11 rounded-xl bg-muted/50 p-1">
          <TabsTrigger value="monitored" className="rounded-lg data-[state=active]:bg-card data-[state=active]:shadow-sm gap-2">
            <Signal className="w-4 h-4" />
            <span className="hidden sm:inline">Currently Monitoring</span>
            <span className="sm:hidden">Monitored</span>
            <span className="tabular-nums text-[11px] opacity-60">({monitoredChannels.length})</span>
          </TabsTrigger>
          <TabsTrigger value="all" className="rounded-lg data-[state=active]:bg-card data-[state=active]:shadow-sm gap-2">
            <Search className="w-4 h-4" />
            <span className="hidden sm:inline">Available Channels</span>
            <span className="sm:hidden">Available</span>
            <span className="tabular-nums text-[11px] opacity-60">
              ({allChannels?.statistics?.total_dialogs ?? '—'})
            </span>
          </TabsTrigger>
        </TabsList>

        {/* ── Monitored Tab ─────────────────────────────────── */}
        <TabsContent value="monitored" className="space-y-4 mt-5">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-8 h-8 animate-spin text-muted-foreground/30" />
            </div>
          ) : monitoredChannels.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed border-border/50 p-12 text-center">
              <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-muted/50 flex items-center justify-center">
                <Signal className="w-7 h-7 text-muted-foreground/30" />
              </div>
              <h3 className="text-base font-semibold mb-2 text-foreground">No Channels Monitored</h3>
              <p className="text-sm text-muted-foreground/60 mb-5 max-w-sm mx-auto">
                Switch to the Available tab to add signal channels for the bot to monitor
              </p>
              <Button onClick={() => setActiveTab('all')} className="rounded-xl" variant="default">
                <Sparkles className="w-4 h-4 mr-2" />Browse Available Channels
              </Button>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {monitoredChannels.map((channel) => renderMonitoredChannelCard(channel))}
            </div>
          )}
        </TabsContent>

        {/* ── All Available Tab ─────────────────────────────── */}
        <TabsContent value="all" className="space-y-5 mt-5">
          {!allChannels ? (
            <div className="rounded-xl border-2 border-dashed border-border/50 p-12 text-center">
              <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-muted/50 flex items-center justify-center">
                <Radio className="w-7 h-7 text-muted-foreground/30" />
              </div>
              <h3 className="text-base font-semibold mb-2 text-foreground">Fetch Channels from Telegram</h3>
              <p className="text-sm text-muted-foreground/60 mb-5 max-w-sm mx-auto">
                Load all channels, groups, and chats accessible from your Telegram account
              </p>
              <Button onClick={fetchAllChannels} disabled={fetchingAll} className="rounded-xl" variant="default">
                {fetchingAll ? (
                  <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Fetching...</>
                ) : (
                  <><RefreshCw className="w-4 h-4 mr-2" />Fetch All Channels</>
                )}
              </Button>
            </div>
          ) : (
            <>
              {/* Stats */}
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
                {statCards.map((stat) => {
                  const styles = statToneStyles[stat.tone]
                  return (
                    <div key={stat.label}
                      className="relative rounded-xl border border-border/40 bg-card/60 backdrop-blur-sm
                        overflow-hidden transition-all duration-200 hover:shadow-sm">
                      <div className="p-3.5 text-center">
                        <div className={`text-2xl font-bold tabular-nums tracking-tight ${styles.text}`}>
                          {stat.value}
                        </div>
                        <div className="text-[11px] text-muted-foreground/50 mt-0.5 font-medium uppercase tracking-wider">
                          {stat.label}
                        </div>
                      </div>
                      <div className={`absolute top-0 left-4 right-4 h-0.5 rounded-full ${styles.bg}`} />
                    </div>
                  )
                })}
              </div>

              {/* Refresh + Search */}
              <div className="flex items-center gap-3">
                <Button variant="outline" size="sm" onClick={refreshAllChannels} disabled={fetchingAll}
                  className="h-9 rounded-xl gap-1.5 shrink-0"
                  title="Re-fetch channel list from Telegram (use if channels are missing)">
                  {fetchingAll ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                  Refresh from Telegram
                </Button>
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/40" />
                  <Input placeholder="Search channels by name or username..." value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-10 h-9 rounded-xl bg-muted/40 border-border/50 focus-visible:ring-1 focus-visible:ring-primary/30" />
                </div>
              </div>

              {/* Broadcast Channels */}
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Broadcast Channels</span>
                  <span className="text-[11px] text-muted-foreground/40 bg-muted/40 px-1.5 py-0.5 rounded-full">{allChannels.channels.length}</span>
                </div>
                {filterChannels(allChannels.channels).length === 0 ? (
                  <p className="text-sm text-muted-foreground/40 text-center py-10">No channels found matching your search</p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {filterChannels(allChannels.channels).map((channel) =>
                      renderChannelCard(channel, isChannelMonitored(channel.id))
                    )}
                  </div>
                )}
              </div>

              {/* Supergroups */}
              {allChannels.supergroups.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Supergroups</span>
                    <span className="text-[11px] text-muted-foreground/40 bg-muted/40 px-1.5 py-0.5 rounded-full">{allChannels.supergroups.length}</span>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {filterChannels(allChannels.supergroups).map((channel) =>
                      renderChannelCard(channel, isChannelMonitored(channel.id))
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </TabsContent>
      </Tabs>

      {/* Add Dialog */}
      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent className="max-w-sm rounded-2xl">
          <DialogHeader>
            <DialogTitle>Add Channel to Monitoring</DialogTitle>
            <DialogDescription>The bot will scan this channel for trading signals.</DialogDescription>
          </DialogHeader>
          {selectedChannel && (
            <div className="py-2">
              <div className="flex items-center gap-3 p-3.5 rounded-xl bg-muted/50 border border-border/30">
                <div className="w-11 h-11 rounded-full bg-gradient-to-br from-blue-500/30 to-purple-600/30
                  flex items-center justify-center text-lg shrink-0 ring-2 ring-border/30">
                  {selectedChannel.broadcast ? '📢' : '💬'}
                </div>
                <div className="min-w-0">
                  <h4 className="font-semibold text-sm truncate">{selectedChannel.title}</h4>
                  {selectedChannel.username && <p className="text-xs text-muted-foreground">@{selectedChannel.username}</p>}
                  {selectedChannel.participants_count != null && selectedChannel.participants_count > 0 && (
                    <p className="text-[11px] text-muted-foreground/50">{selectedChannel.participants_count.toLocaleString()} members</p>
                  )}
                </div>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddDialog(false)} className="rounded-xl">Cancel</Button>
            <Button onClick={() => selectedChannel && addChannelToMonitoring(selectedChannel)} className="rounded-xl">
              <Plus className="w-4 h-4 mr-1.5" />Add Channel
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
