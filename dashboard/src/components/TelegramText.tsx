'use client'

import { Fragment, useMemo, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { parseTelegramMarkdown, type Entity } from '@/lib/telegramMarkdown'

// Renders a Telegram message (Telethon markdown) the way Telegram shows it.
// For AI-written CommonMark use <Markdown> instead.
//   inline → collapse line breaks (one-line previews, used with `truncate`)
export default function TelegramText({
  text,
  className,
  inline,
}: {
  text: string | null | undefined
  className?: string
  inline?: boolean
}) {
  const nodes = useMemo(() => render(text ?? ''), [text])
  return (
    <div className={cn(inline ? 'whitespace-normal' : 'whitespace-pre-wrap', 'break-words', className)}>
      {nodes}
    </div>
  )
}

function render(input: string): ReactNode[] {
  const { text, entities } = parseTelegramMarkdown(input)
  if (!entities.length) return [text]

  const cuts = new Set([0, text.length])
  for (const e of entities) {
    cuts.add(e.offset)
    cuts.add(e.offset + e.length)
  }
  const points = [...cuts].sort((a, b) => a - b)

  const out: ReactNode[] = []
  for (let k = 0; k < points.length - 1; k++) {
    const [a, b] = [points[k], points[k + 1]]
    if (a === b) continue
    const active = entities.filter((e) => e.offset <= a && e.offset + e.length >= b)
    out.push(<Fragment key={a}>{wrap(text.slice(a, b), active)}</Fragment>)
  }
  return out
}

const has = (es: Entity[], t: Entity['type']) => es.find((e) => e.type === t)

function wrap(chunk: string, es: Entity[]): ReactNode {
  let node: ReactNode = chunk
  if (has(es, 'pre')) {
    node = <code className="block font-mono text-[0.85em] bg-muted/70 rounded-md px-2.5 py-1.5 my-1 overflow-x-auto">{node}</code>
  } else if (has(es, 'code')) {
    node = <code className="font-mono text-[0.85em] bg-muted/70 rounded px-1 py-0.5">{node}</code>
  }
  if (has(es, 'spoiler')) {
    node = (
      <span className="rounded bg-foreground/15 blur-[3px] hover:blur-0 transition-[filter] cursor-pointer" title="Spoiler">
        {node}
      </span>
    )
  }
  if (has(es, 'strike')) node = <del className="opacity-70">{node}</del>
  if (has(es, 'italic')) node = <em>{node}</em>
  if (has(es, 'bold')) node = <strong className="font-semibold">{node}</strong>
  const link = has(es, 'link')
  if (link?.url && /^(https?:|tg:|mailto:)/i.test(link.url)) {
    node = (
      <a href={link.url} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2 break-all">
        {node}
      </a>
    )
  }
  return node
}
