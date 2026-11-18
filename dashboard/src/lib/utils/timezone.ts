/**
 * Time zone conversion utilities for broker time vs user local time
 */

/**
 * Convert broker timestamp (UTC) to user's local time
 * @param timestamp - Unix timestamp in seconds or milliseconds
 * @returns Date object in user's local timezone
 */
export function brokerTimeToLocal(timestamp: number): Date {
  // Handle both seconds and milliseconds
  const timeInMs = timestamp < 10000000000 ? timestamp * 1000 : timestamp;
  return new Date(timeInMs);
}

/**
 * Convert user's local time to broker timestamp (UTC)
 * @param date - Date object in user's local timezone
 * @returns Unix timestamp in milliseconds
 */
export function localToBrokerTime(date: Date): number {
  return date.getTime();
}

/**
 * Format broker timestamp for display in user's local timezone
 * @param timestamp - Unix timestamp in seconds or milliseconds
 * @param format - Format string (default: 'YYYY-MM-DD HH:mm:ss')
 * @returns Formatted date string
 */
export function formatBrokerTime(
  timestamp: number,
  format: 'date' | 'datetime' | 'time' = 'datetime'
): string {
  const date = brokerTimeToLocal(timestamp);
  
  const options: Intl.DateTimeFormatOptions = {
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  };

  switch (format) {
    case 'date':
      options.year = 'numeric';
      options.month = '2-digit';
      options.day = '2-digit';
      break;
    case 'time':
      options.hour = '2-digit';
      options.minute = '2-digit';
      options.second = '2-digit';
      options.hour12 = false;
      break;
    case 'datetime':
    default:
      options.year = 'numeric';
      options.month = '2-digit';
      options.day = '2-digit';
      options.hour = '2-digit';
      options.minute = '2-digit';
      options.second = '2-digit';
      options.hour12 = false;
      break;
  }

  return new Intl.DateTimeFormat(undefined, options).format(date);
}

/**
 * Get the time difference between broker time (UTC) and user's local time in hours
 * @returns Offset in hours (positive if local time is ahead of UTC)
 */
export function getTimeZoneOffset(): number {
  const offset = new Date().getTimezoneOffset();
  return -offset / 60; // Convert minutes to hours and invert sign
}

/**
 * Convert TradingView chart time format (seconds) to broker timestamp
 * @param tvTime - TradingView time in seconds
 * @returns Unix timestamp in seconds
 */
export function tvTimeToBrokerTime(tvTime: number): number {
  return tvTime;
}

/**
 * Convert broker timestamp to TradingView chart time format (seconds)
 * @param brokerTime - Unix timestamp in seconds or milliseconds
 * @returns Time in seconds for TradingView
 */
export function brokerTimeToTvTime(brokerTime: number): number {
  // If in milliseconds, convert to seconds
  return brokerTime < 10000000000 ? brokerTime : brokerTime / 1000;
}
