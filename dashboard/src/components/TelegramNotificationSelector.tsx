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
  Bell,
} from 'lucide-react'

// Use Next.js API routes (server-to-server) instead of direct backend calls

interface TelegramChannel {
  title: string
  username?: string
  id: string
  access_hash?: string
  megagroup: boolean
  broadcast: boolean
  participants_count?: number
  photo_url?: string | null
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
  private_chats: any[]
}

interface Props {
  currentValue: string // Single channel ID
  onChange: (newValue: string) => void
  sharedChannels?: ChannelData | null // Shared channels from parent
  onFetchChannels?: () => Promise<void> // Parent's fetch function
  isLoading?: boolean // Parent's loading state
}

// Helper to normalize channel ID for comparison
const normalizeChannelId = (id: string): string => {
  // Remove any whitespace
  const trimmed = id.trim()
  
  // If it starts with -100, return as is
  if (trimmed.startsWith('-100')) {
    return trimmed
  }
  
  // If it's a negative number without -100 prefix, add it
  if (trimmed.startsWith('-')) {
    return `-100${trimmed.substring(1)}`
  }
  
  // If it's a positive number, add -100 prefix
  return `-100${trimmed}`
}

// Helper to check if two IDs match (handles different formats)
const idsMatch = (id1: string, id2: string): boolean => {
  const normalized1 = normalizeChannelId(id1)
  const normalized2 = normalizeChannelId(id2)
  return normalized1 === normalized2
}

export default function TelegramNotificationSelector({ 
  currentValue, 
  onChange,
  sharedChannels,
  onFetchChannels,
  isLoading = false
}: Props) {
  const [selectedChannelId, setSelectedChannelId] = useState<string>('')
  const [searchQuery, setSearchQuery] = useState('')
  const { toast } = useToast()
  const hasLoadedRef = useRef(false)
  const [showAvailableChannels, setShowAvailableChannels] = useState(false)
  
  // Use shared channels from parent
  const allChannels = sharedChannels
  const loading = isLoading

  // Load channels from cache using parent's fetch function
  const loadChannelsFromCache = useCallback(async () => {
    if (onFetchChannels) {
      try {
        await onFetchChannels()
      } catch (error) {
        console.error('Error loading channels:', error)
        toast({
          variant: 'destructive',
          title: 'Error',
          description: 'Failed to load channels',
        })
      }
    }
  }, [onFetchChannels, toast])

  // Fetch all channels from Telegram (refresh cache)
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
        toast({
          variant: 'destructive',
          title: 'Error',
          description: 'Failed to fetch channels',
        })
      }
    }
  }

  // Parse current value and load channel details from cache
  useEffect(() => {
    const channelId = currentValue || ''
    setSelectedChannelId(channelId)
    
    // Load from cache to get channel names/details
    if (channelId && !hasLoadedRef.current) {
      hasLoadedRef.current = true
      loadChannelsFromCache()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentValue])

  // Select channel (single selection)
  const selectChannel = (channelId: string) => {
    const normalizedId = normalizeChannelId(channelId)  // Normalize to -100 format
    setSelectedChannelId(normalizedId)
    onChange(normalizedId)
  }

  // Get selected channel with details
  const getSelectedChannel = () => {
    if (!selectedChannelId) return null
    
    if (!allChannels) {
      // If channels not fetched yet, return placeholder object with just ID
      return {
        id: selectedChannelId,
        title: `Channel ID: ${selectedChannelId}`,
        broadcast: true,
        megagroup: false,
        username: undefined,
        access_hash: undefined,
        participants_count: undefined,
        photo_url: null
      }
    }
    
    const allAvailable = [
      ...(allChannels.channels || []),
      ...(allChannels.supergroups || []),
      ...(allChannels.groups || []),
      ...(allChannels.private_chats || [])
    ]
    
    // Try to find using ID matching
    const found = allAvailable.find(ch => idsMatch(ch.id, selectedChannelId))
    if (found) {
      return found
    }
    
    // If not found, return a placeholder
    return {
      id: selectedChannelId,
      title: `Channel ID: ${selectedChannelId}`,
      broadcast: true,
      megagroup: false,
      username: undefined,
      access_hash: undefined,
      participants_count: undefined,
      photo_url: null
    }
  }

  // Filter channels based on search
  const filterChannels = (channels: TelegramChannel[]) => {
    if (!searchQuery) return channels
    const query = searchQuery.toLowerCase()
    return channels.filter(
      (ch) =>
        ch.title.toLowerCase().includes(query) ||
        (ch.username && ch.username.toLowerCase().includes(query))
    )
  }

  const selectedChannel = getSelectedChannel()

  return (
    <div className="space-y-4">
      {/* Currently Selected Notification Channel - Always Show */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold flex items-center gap-2">
            <Bell className="w-4 h-4 text-primary" />
            Current Notification Channel
          </h4>
          {selectedChannel && (
            <Badge variant="outline" className="bg-primary/10 text-primary border-blue-200">
              <CheckCircle2 className="w-3 h-3 mr-1" />
              Active
            </Badge>
          )}
        </div>
        
        {!selectedChannel ? (
          <Card className="border-dashed border-2 border-border">
            <CardContent className="p-6 text-center">
              <div className="text-muted-foreground/70 text-sm">
                <Bell className="w-8 h-8 mx-auto mb-2 opacity-50" />
                <p className="font-semibold">No notification channel selected</p>
                <p className="text-xs mt-1">Click "Select Notification Channel" below to choose where notifications are sent</p>
              </div>
            </CardContent>
          </Card>
        ) : (
          <Card className="border-2 border-blue-200 bg-primary/10/50">
            <CardContent className="p-3">
              <div className="flex items-center gap-3">
                {selectedChannel.photo_url ? (
                  <img 
                    src={selectedChannel.photo_url} 
                    alt={selectedChannel.title}
                    className="w-10 h-10 rounded-full object-cover flex-shrink-0 border-2 border-blue-400"
                  />
                ) : (
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white text-lg font-bold flex-shrink-0">
                    {selectedChannel.broadcast ? '📢' : '💬'}
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold truncate">{selectedChannel.title}</p>
                  {selectedChannel.username && (
                    <p className="truncate text-xs text-muted-foreground">@{selectedChannel.username}</p>
                  )}
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1">
                    {selectedChannel.participants_count && (
                      <Badge variant="secondary" className="text-xs">
                        <Users className="w-3 h-3 mr-1" />
                        {selectedChannel.participants_count.toLocaleString()}
                      </Badge>
                    )}
                    <Badge className="text-xs bg-blue-600">
                      Receiving Notifications
                    </Badge>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Fetch Channels Button */}
      {!showAvailableChannels ? (
        <Button
          onClick={fetchAllChannels}
          disabled={loading}
          variant="outline"
          className="w-full"
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Fetching Channels...
            </>
          ) : (
            <>
              <RefreshCw className="w-4 h-4 mr-2" />
              Select Notification Channel
            </>
          )}
        </Button>
      ) : allChannels ? (
        <>
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search channels by name or username..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10"
            />
          </div>

          {/* Available Channels */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-semibold">
                Available Channels ({(allChannels?.statistics?.channels || 0) + (allChannels?.statistics?.supergroups || 0) + (allChannels?.statistics?.private_chats || 0)})
              </h4>
              <Button
                onClick={fetchAllChannels}
                variant="ghost"
                size="sm"
                disabled={loading}
              >
                <RefreshCw className="w-3 h-3" />
              </Button>
            </div>

            {/* Columns follow the width of this panel, not of the window: in a
                half-width settings column three columns left no room for the cards. */}
            <div className="max-h-96 overflow-y-auto overflow-x-hidden">
              <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,230px),1fr))] gap-2">
              {filterChannels([
                ...(allChannels?.channels || []),
                ...(allChannels?.supergroups || []),
                ...(allChannels?.private_chats || [])
              ]).map((channel) => {
                const isSelected = idsMatch(selectedChannelId, channel.id)
                return (
                  <Card
                    key={channel.id}
                    className={`min-w-0 cursor-pointer transition-all ${
                      isSelected 
                        ? 'border-2 border-blue-500 bg-primary/10 shadow-md' 
                        : 'hover:border-gray-300 hover:shadow-sm'
                    }`}
                    onClick={() => selectChannel(channel.id)}
                  >
                    <CardContent className="p-3">
                      <div className="flex items-center gap-3">
                        {channel.photo_url ? (
                          <img 
                            src={channel.photo_url} 
                            alt={channel.title}
                            className={`w-10 h-10 rounded-full object-cover flex-shrink-0 ${
                              isSelected ? 'border-2 border-blue-500' : 'border border-border'
                            }`}
                          />
                        ) : (
                          <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white text-lg font-bold flex-shrink-0 ${
                            isSelected 
                              ? 'bg-gradient-to-br from-blue-600 to-indigo-600' 
                              : 'bg-gradient-to-br from-blue-500 to-purple-600'
                          }`}>
                            {channel.broadcast ? '📢' : '💬'}
                          </div>
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-semibold truncate">{channel.title}</p>
                            {isSelected && (
                              <CheckCircle2 className="w-4 h-4 text-primary flex-shrink-0" />
                            )}
                          </div>
                          {channel.username && (
                            <p className="truncate text-xs text-muted-foreground">@{channel.username}</p>
                          )}
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1">
                            {channel.participants_count && (
                              <Badge variant="secondary" className="text-xs">
                                <Users className="w-3 h-3 mr-1" />
                                {channel.participants_count.toLocaleString()}
                              </Badge>
                            )}
                            {channel.broadcast && (
                              <Badge variant="outline" className="text-xs">
                                <Radio className="w-3 h-3 mr-1" />
                                Channel
                              </Badge>
                            )}
                            {isSelected && (
                              <Badge className="text-xs bg-blue-600">
                                Selected
                              </Badge>
                            )}
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}
