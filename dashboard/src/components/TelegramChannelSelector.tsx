'use client'

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/hooks/use-toast'
import {
  Search,
  RefreshCw,
  Loader2,
  Radio,
  Users,
  CheckCircle2,
  Plus,
  X,
  AlertTriangle,
} from 'lucide-react'

// ─── Types ──────────────────────────────────────────────────────────────────

interface TelegramChannel {
  title: string
  username?: string
  id: string
  access_hash?: string
  megagroup: boolean
  broadcast: boolean
  participants_count?: number
  photo_url?: string | null
  /** Set for channels of another source (Discord): the id is used exactly as it is. */
  source?: 'discord'
}

/** A channel that is not a Telegram dialog — a Discord channel selected on the Discord page. */
export interface ExtraChannel {
  id: string
  title: string
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
}

interface Props {
  currentValue: string
  onChange: (newValue: string) => void
  sharedChannels?: ChannelData | null
  onFetchChannels?: () => Promise<void>
  onRefreshChannels?: () => Promise<void>
  isLoading?: boolean
  allowedChannelIds?: string
  /** Discord channels offered next to the Telegram ones (never filtered by allowedChannelIds). */
  extraChannels?: ExtraChannel[]
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const normalizeChannelId = (id: string): string => {
  const trimmed = id.trim()
  if (trimmed.startsWith('-100')) return trimmed
  if (trimmed.startsWith('-')) return `-100${trimmed.substring(1)}`
  return `-100${trimmed}`
}

const idsMatch = (id1: string, id2: string): boolean =>
  normalizeChannelId(id1) === normalizeChannelId(id2)

// ─── Component ───────────────────────────────────────────────────────────────

export default function TelegramChannelSelector({
  currentValue,
  onChange,
  sharedChannels,
  onFetchChannels,
  onRefreshChannels,
  isLoading = false,
  allowedChannelIds,
  extraChannels,
}: Props) {
  const [selectedChannelIds, setSelectedChannelIds] = useState<string[]>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [showAvailableChannels, setShowAvailableChannels] = useState(false)
  const { toast } = useToast()
  const hasLoadedRef = useRef(false)

  const allChannels = sharedChannels
  const loading = isLoading

  // Discord ids are stored and compared exactly as they are: the "-100" normalisation
  // below is Telegram's and would turn a Discord id into one that never matches.
  const extras: TelegramChannel[] = (extraChannels ?? []).map((c) => ({
    id: c.id, title: c.title, broadcast: false, megagroup: false, source: 'discord',
  }))
  const extraIds = new Set(extras.map((c) => c.id))
  const sameChannel = (a: string, b: string): boolean =>
    extraIds.has(a.trim()) || extraIds.has(b.trim()) ? a.trim() === b.trim() : idsMatch(a, b)
  const storedId = (id: string): string => (extraIds.has(id.trim()) ? id.trim() : normalizeChannelId(id))

  // Load channels from cache
  const loadChannelsFromCache = useCallback(async () => {
    if (onFetchChannels) {
      try {
        await onFetchChannels()
      } catch (error) {
        console.error('Error loading channels:', error)
        toast({ variant: 'destructive', title: 'Error', description: 'Failed to load channels' })
      }
    }
  }, [onFetchChannels, toast])

  // Fetch all channels from Telegram
  const fetchAllChannels = async () => {
    setShowAvailableChannels(true)
    if (onFetchChannels) {
      try {
        await onFetchChannels()
        if (allChannels) {
          toast({
            title: 'Channels Loaded',
            description: `Found ${allChannels.statistics?.total_dialogs || 0} channels.`,
          })
        }
      } catch (error) {
        console.error('Error fetching channels:', error)
        toast({ variant: 'destructive', title: 'Error', description: 'Failed to fetch channels' })
      }
    }
  }

  // Parse current value
  useEffect(() => {
    const stringValue = Array.isArray(currentValue)
      ? currentValue.join(',')
      : (currentValue || '')
    const ids = stringValue
      ? stringValue.split(',').map((id) => id.trim()).filter(Boolean)
      : []
    setSelectedChannelIds(ids)
    if (ids.length > 0 && !hasLoadedRef.current) {
      hasLoadedRef.current = true
      loadChannelsFromCache()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentValue])

  // Toggle channel selection
  const toggleChannel = (channelId: string) => {
    const isCurrentlySelected = selectedChannelIds.some((id) => sameChannel(id, channelId))
    const newIds = isCurrentlySelected
      ? selectedChannelIds.filter((id) => !sameChannel(id, channelId))
      : [...selectedChannelIds, storedId(channelId)]
    setSelectedChannelIds(newIds)
    onChange(newIds.join(','))
  }

  // Get selected channels with details
  const getSelectedChannels = () => {
    if (!allChannels) {
      return selectedChannelIds.map((id) => extras.find((c) => c.id === id.trim()) ?? ({
        id,
        title: `Channel ID: ${id}`,
        broadcast: true,
        megagroup: false,
        username: undefined,
        access_hash: undefined,
        participants_count: undefined,
        photo_url: null,
      } as TelegramChannel))
    }
    const allAvailable = [
      ...(allChannels.channels || []),
      ...(allChannels.supergroups || []),
      ...(allChannels.groups || []),
    ]
    const uniqueChannels = new Map<string, TelegramChannel>()
    selectedChannelIds.forEach((id) => {
      const extra = extras.find((c) => c.id === id.trim())
      if (extra) {
        uniqueChannels.set(extra.id, extra)
        return
      }
      const found = allAvailable.find((ch) => idsMatch(ch.id, id))
      if (found) {
        const normalizedId = normalizeChannelId(found.id)
        if (!uniqueChannels.has(normalizedId)) uniqueChannels.set(normalizedId, found)
      } else {
        const normalizedId = normalizeChannelId(id)
        if (!uniqueChannels.has(normalizedId)) {
          uniqueChannels.set(normalizedId, {
            id,
            title: `Channel ID: ${id}`,
            broadcast: true,
            megagroup: false,
            username: undefined,
            access_hash: undefined,
            participants_count: undefined,
            photo_url: null,
          })
        }
      }
    })
    return Array.from(uniqueChannels.values())
  }

  // Filter channels
  const filterChannels = (channels: TelegramChannel[]) => {
    let filtered = channels
    if (allowedChannelIds) {
      const stringValue = Array.isArray(allowedChannelIds)
        ? allowedChannelIds.join(',')
        : allowedChannelIds
      const allowedIds = stringValue.split(',').map((id) => id.trim()).filter(Boolean)
      filtered = filtered.filter((ch) =>
        allowedIds.some((allowedId) => idsMatch(ch.id, allowedId))
      )
    }
    filtered = [...filtered, ...extras]
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      filtered = filtered.filter(
        (ch) =>
          ch.title.toLowerCase().includes(query) ||
          (ch.username && ch.username.toLowerCase().includes(query))
      )
    }
    return filtered
  }

  const selectedChannels = getSelectedChannels()

  // ─── Shared card styles ──────────────────────────────────────────────────

  // Ring color for selected cards — uses CSS variable emerald in both modes
  const selectedRing = 'ring-2 ring-emerald-500/60 dark:ring-emerald-400/50'
  const selectedBg = 'bg-emerald-50/80 dark:bg-emerald-950/40'
  const selectedBorder = 'border-emerald-200 dark:border-emerald-800/60'

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5">
      {/* ── Currently Monitoring ─────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-1.5 h-5 rounded-full bg-emerald-500 dark:bg-emerald-400" />
            <h4 className="text-sm font-semibold tracking-tight text-foreground">
              Currently Monitoring
            </h4>
            <span className="text-xs font-medium text-muted-foreground tabular-nums">
              {selectedChannels.length}
            </span>
          </div>
          {selectedChannels.length > 0 && (
            <Badge
              variant="outline"
              className="border-emerald-500/40 text-emerald-600 dark:text-emerald-400 bg-emerald-50/60 dark:bg-emerald-950/40 text-[11px] font-medium"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400 mr-1.5" />
              Active
            </Badge>
          )}
        </div>

        {selectedChannels.length === 0 ? (
          <div className="rounded-xl border-2 border-dashed border-border/60 p-8 text-center">
            <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-muted/60 flex items-center justify-center">
              <AlertTriangle className="w-5 h-5 text-muted-foreground/50" />
            </div>
            <p className="text-sm font-medium text-muted-foreground">No channels selected</p>
            <p className="text-xs text-muted-foreground/60 mt-1">
              Click &ldquo;Fetch Available Channels&rdquo; below to start monitoring
            </p>
          </div>
        ) : (
          /* Columns follow the width of this panel, not of the window: in a half-width
             settings column five columns left only the avatar visible. */
          <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,180px),1fr))] gap-2.5">
            {selectedChannels.map((channel) => (
              <div
                key={channel.id}
                className={`relative group min-w-0 rounded-xl border bg-card/80 backdrop-blur-sm transition-all duration-200 ease-out
                  ${selectedRing} ${selectedBorder} ${selectedBg}
                  hover:shadow-md dark:hover:shadow-emerald-950/30`}
              >
                <div className="p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      {/* Avatar */}
                      {channel.photo_url ? (
                        <img
                          src={channel.photo_url}
                          alt={channel.title}
                          className="w-8 h-8 rounded-full object-cover shrink-0 ring-2 ring-emerald-400/40 dark:ring-emerald-500/30"
                        />
                      ) : (
                        <div className="w-8 h-8 rounded-full bg-emerald-100 dark:bg-emerald-900/50 flex items-center justify-center text-sm shrink-0 font-medium text-emerald-600 dark:text-emerald-400">
                          {channel.source === 'discord' ? '🎮' : channel.broadcast ? '📢' : '💬'}
                        </div>
                      )}
                      <div className="min-w-0">
                        <p className="text-xs font-semibold truncate text-foreground leading-tight">
                          {channel.title}
                        </p>
                        {channel.username && (
                          <p className="text-[10px] text-muted-foreground/70 truncate">
                            @{channel.username}
                          </p>
                        )}
                        {channel.source === 'discord' && (
                          <p className="text-[10px] text-muted-foreground/70 truncate">Discord</p>
                        )}
                      </div>
                    </div>
                    <button
                      onClick={() => toggleChannel(channel.id)}
                      className="shrink-0 w-6 h-6 rounded-full flex items-center justify-center
                        text-muted-foreground/40 hover:text-red-500 dark:hover:text-red-400
                        hover:bg-red-50 dark:hover:bg-red-950/40
                        opacity-0 group-hover:opacity-100 transition-all duration-150"
                      title="Remove from monitoring"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Fetch / Available Channels ───────────────────────── */}
      {!showAvailableChannels ? (
        <Button
          onClick={fetchAllChannels}
          disabled={loading}
          variant="outline"
          className="w-full h-10 rounded-xl border-dashed border-border/70 text-muted-foreground hover:text-foreground hover:border-primary/40 hover:bg-primary/5 transition-all duration-200"
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Fetching Channels...
            </>
          ) : (
            <>
              <RefreshCw className="w-4 h-4 mr-2" />
              Fetch Available Channels
            </>
          )}
        </Button>
      ) : allChannels || extras.length > 0 ? (
        <div className="space-y-4">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
            <Input
              placeholder="Search channels by name or username..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10 h-10 rounded-xl bg-muted/40 border-border/50 focus-visible:ring-1 focus-visible:ring-primary/30"
            />
          </div>

          {/* Available Channels List */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  Available
                </span>
                <span className="text-[11px] tabular-nums text-muted-foreground/60 bg-muted/50 px-1.5 py-0.5 rounded-full">
                  {(allChannels?.statistics?.channels || 0) +
                    (allChannels?.statistics?.supergroups || 0) + extras.length}
                </span>
              </div>
              {onRefreshChannels && (
                <Button
                  onClick={async () => { await onRefreshChannels() }}
                  variant="ghost"
                  size="sm"
                  disabled={loading}
                  className="h-7 px-2 rounded-full text-[10px] font-semibold text-muted-foreground gap-1"
                  title="Re-fetch all channels from Telegram (picks up newly joined channels)"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                  Refresh from Telegram
                </Button>
              )}
            </div>

            <div className="max-h-96 overflow-y-auto overflow-x-hidden rounded-xl border border-border/40 bg-card/30 backdrop-blur-sm">
              <div className="p-3 grid grid-cols-[repeat(auto-fill,minmax(min(100%,230px),1fr))] gap-2">
                {filterChannels([
                  ...(allChannels?.channels || []),
                  ...(allChannels?.supergroups || []),
                  ...(allChannels?.groups || []),
                ]).map((channel) => {
                  const isSelected = selectedChannelIds.some((id) => sameChannel(id, channel.id))
                  return (
                    <button
                      key={channel.id}
                      onClick={() => toggleChannel(channel.id)}
                      className={`w-full min-w-0 text-left rounded-xl border transition-all duration-200 ease-out
                        ${
                          isSelected
                            ? `${selectedRing} ${selectedBorder} ${selectedBg} shadow-sm`
                            : 'border-border/50 bg-card/60 hover:border-primary/30 hover:bg-accent/40 hover:shadow-sm'
                        }
                      `}
                    >
                      <div className="p-3">
                        <div className="flex items-center gap-3">
                          {/* Avatar */}
                          {channel.photo_url ? (
                            <img
                              src={channel.photo_url}
                              alt={channel.title}
                              className={`w-10 h-10 rounded-full object-cover shrink-0 ring-2 transition-colors ${
                                isSelected
                                  ? 'ring-emerald-400/50 dark:ring-emerald-500/40'
                                  : 'ring-border/40 dark:ring-border/60'
                              }`}
                            />
                          ) : (
                            <div
                              className={`w-10 h-10 rounded-full flex items-center justify-center text-base shrink-0 font-semibold transition-colors ${
                                isSelected
                                  ? 'bg-emerald-100 dark:bg-emerald-900/50 text-emerald-600 dark:text-emerald-400'
                                  : 'bg-gradient-to-br from-blue-500/20 to-purple-600/20 text-blue-600 dark:text-blue-400 dark:from-blue-500/30 dark:to-purple-600/30'
                              }`}
                            >
                              {channel.source === 'discord' ? '🎮' : channel.broadcast ? '📢' : '💬'}
                            </div>
                          )}

                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5">
                              <p className="text-sm font-semibold truncate text-foreground leading-snug">
                                {channel.title}
                              </p>
                              {isSelected && (
                                <CheckCircle2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400 shrink-0" />
                              )}
                            </div>
                            {channel.username && (
                              <p className="text-[11px] text-muted-foreground/60 truncate mt-0.5">
                                @{channel.username}
                              </p>
                            )}
                            <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                              {channel.participants_count != null && channel.participants_count > 0 && (
                                <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground/60 bg-muted/50 px-1.5 py-0.5 rounded-full">
                                  <Users className="w-2.5 h-2.5" />
                                  {channel.participants_count.toLocaleString()}
                                </span>
                              )}
                              {channel.source === 'discord' && (
                                <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground/60 bg-muted/50 px-1.5 py-0.5 rounded-full">
                                  Discord
                                </span>
                              )}
                              {channel.broadcast && (
                                <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground/60 bg-muted/50 px-1.5 py-0.5 rounded-full">
                                  <Radio className="w-2.5 h-2.5" />
                                  Channel
                                </span>
                              )}
                              {isSelected && (
                                <span className="inline-flex items-center gap-1 text-[10px] font-medium text-emerald-600 dark:text-emerald-400 bg-emerald-100/70 dark:bg-emerald-950/50 px-1.5 py-0.5 rounded-full">
                                  Monitoring
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
