'use client'

import React, { useState, useMemo } from 'react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Search, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface SearchableSelectOption {
  value: string
  label: string
  description?: string
}

interface SearchableSelectProps {
  options: SearchableSelectOption[]
  value: string
  onChange: (value: string) => void
  placeholder?: string
  hasChanged?: boolean
  className?: string
}

export default function SearchableSelect({ 
  options, 
  value, 
  onChange, 
  placeholder = "Select option",
  hasChanged,
  className 
}: SearchableSelectProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [isOpen, setIsOpen] = useState(false)

  const filteredOptions = useMemo(() => {
    if (!searchQuery) return options
    const query = searchQuery.toLowerCase()
    return options.filter(opt => 
      opt.label.toLowerCase().includes(query) || 
      opt.value.toLowerCase().includes(query) ||
      (opt.description && opt.description.toLowerCase().includes(query))
    )
  }, [options, searchQuery])

  const selectedOption = options.find(opt => opt.value === value)

  const handleClearSearch = () => {
    setSearchQuery('')
  }

  return (
    <div className="flex flex-col gap-1.5">
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
            className
          )}
        >
          <SelectValue placeholder={placeholder}>
            {selectedOption && (
              <div className="flex items-center gap-2">
                <span className="font-semibold">{selectedOption.label}</span>
              </div>
            )}
          </SelectValue>
        </SelectTrigger>
        <SelectContent className="max-h-80">
          {/* Search input inside dropdown */}
          <div className="p-2 border-b">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
              <Input
                placeholder="Search providers..."
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
          
          {/* Filtered options */}
          <div className="max-h-60 overflow-y-auto">
            {filteredOptions.length === 0 ? (
              <div className="py-4 text-center text-xs text-muted-foreground">
                No providers found
              </div>
            ) : (
              filteredOptions.map((option) => (
                <SelectItem 
                  key={option.value} 
                  value={option.value} 
                  className="text-xs py-2"
                >
                  <div className="flex flex-col">
                    <span className="font-semibold">{option.label}</span>
                    {option.description && (
                      <span className="text-[10px] text-muted-foreground line-clamp-1">
                        {option.description}
                      </span>
                    )}
                  </div>
                </SelectItem>
              ))
            )}
          </div>
        </SelectContent>
      </Select>
    </div>
  )
}
