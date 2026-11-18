// Telegram message text is stored in Telethon's markdown dialect, not CommonMark:
// "**GOLD SELL NOW **" (space before the closing marker) and bold spanning blank
// lines are normal there, and a CommonMark renderer prints them as literal stars.
// This parser follows Telegram's rule instead: a marker pairs with the next
// identical marker, whatever is in between. Output is plain text plus entities
// (offset/length), the same model Telegram uses.

export type EntityType = 'bold' | 'italic' | 'strike' | 'spoiler' | 'code' | 'pre' | 'link'

export interface Entity {
  type: EntityType
  offset: number
  length: number
  url?: string
}

const DELIMS: [string, EntityType][] = [
  ['```', 'pre'],
  ['**', 'bold'],
  ['__', 'italic'],
  ['~~', 'strike'],
  ['||', 'spoiler'],
  ['`', 'code'],
]

const LINK = /^\[([^\]\n]+)\]\(([^)\s]+)\)/

export function parseTelegramMarkdown(input: string): { text: string; entities: Entity[] } {
  // Learned patterns are cut at 200 chars + "...", sometimes mid-marker ("**GOLD SIGNAL*...")
  let msg = (input ?? '').replace(/[*_~|`]+(\.\.\.)$/, '$1')
  const entities: Entity[] = []

  // Remove msg[pos, pos+len) and shift/shrink the entities already found
  const cut = (pos: number, len: number) => {
    msg = msg.slice(0, pos) + msg.slice(pos + len)
    for (const e of entities) {
      const end = e.offset + e.length
      const overlap = Math.max(0, Math.min(end, pos + len) - Math.max(e.offset, pos))
      if (pos < e.offset) e.offset -= Math.min(len, e.offset - pos)
      e.length -= overlap
    }
  }

  let i = 0
  while (i < msg.length) {
    if (msg[i] === '[') {
      const m = LINK.exec(msg.slice(i))
      if (m) {
        const [, label, url] = m
        cut(i + 1 + label.length, url.length + 3) // "](url)"
        cut(i, 1) // "["
        entities.push({ type: 'link', offset: i, length: label.length, url })
        continue // the label may carry its own formatting
      }
    }

    const hit = DELIMS.find(([d]) => msg.startsWith(d, i))
    if (hit) {
      const [d, type] = hit
      const end = msg.indexOf(d, i + d.length)
      if (end > i + d.length) {
        cut(end, d.length)
        cut(i, d.length)
        let length = end - i - d.length
        if (type === 'pre' && msg[i] === '\n') {
          cut(i, 1)
          length -= 1
        }
        entities.push({ type, offset: i, length })
        // Code is literal; everything else may nest more formatting
        if (type === 'code' || type === 'pre') i += length
        continue
      }
      cut(i, d.length) // unpaired (e.g. text cut off mid-format): drop the marker
      continue
    }
    i++
  }

  return { text: msg, entities: entities.filter((e) => e.length > 0) }
}

/** The message as plain text (markers and link targets removed). */
export const telegramPlainText = (input: string) => parseTelegramMarkdown(input).text
