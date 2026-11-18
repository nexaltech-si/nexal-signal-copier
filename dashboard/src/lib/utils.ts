import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatCurrency(amount: number, currency: string = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency.toUpperCase(),
  }).format(amount)
}

export function formatDate(date: string | Date): string {
  return new Intl.DateTimeFormat('en-GB', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(date))
}

export function formatPips(pips: number | null | undefined): string {
  if (pips === null || pips === undefined) return 'N/A'
  return `${pips >= 0 ? '+' : ''}${pips.toFixed(1)} pips`
}

export function getStatusColor(status: string): string {
  const statusColors: Record<string, string> = {
    PENDING: 'bg-yellow-100 text-yellow-800',
    VALIDATED: 'bg-green-100 text-green-800',
    AWAITING_APPROVAL: 'bg-orange-100 text-orange-800',
    PROCESSING: 'bg-blue-100 text-blue-800',
    EXECUTED: 'bg-blue-100 text-blue-800',
    EXECUTING: 'bg-blue-100 text-blue-800',
    CLOSED: 'bg-gray-100 text-gray-800',
    REJECTED: 'bg-red-100 text-red-800',
    EXPIRED: 'bg-gray-100 text-gray-600',
    FAILED: 'bg-red-100 text-red-800',
  }
  return statusColors[status] || 'bg-gray-100 text-gray-800'
}
