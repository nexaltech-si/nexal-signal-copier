'use client'

import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

function cn(...c: (string | undefined | false)[]) {
  return c.filter(Boolean).join(' ')
}

// Shared element map so every chat surface (Hermes, Telegram browser) renders
// Markdown identically, using the dashboard's Tailwind design tokens.
export const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  h1: ({ children }) => <h1 className="text-base font-bold mt-3 mb-1.5 first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="text-sm font-bold mt-3 mb-1.5 first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold mt-2 mb-1 first:mt-0">{children}</h3>,
  ul: ({ children }) => <ul className="list-disc pl-5 mb-2 space-y-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 space-y-0.5">{children}</ol>,
  li: ({ children }) => <li className="marker:text-muted-foreground">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  del: ({ children }) => <del className="line-through opacity-70">{children}</del>,
  a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2 break-all">{children}</a>,
  blockquote: ({ children }) => <blockquote className="border-l-2 border-primary/40 pl-3 italic text-muted-foreground my-2">{children}</blockquote>,
  hr: () => <hr className="border-border my-3" />,
  code: ({ className, children }) =>
    className ? (
      <code className={cn('block bg-muted p-2 rounded text-[0.8em] font-mono overflow-x-auto', className)}>{children}</code>
    ) : (
      <code className="bg-muted px-1 py-0.5 rounded text-[0.85em] font-mono">{children}</code>
    ),
  pre: ({ children }) => <pre className="bg-muted rounded-lg my-2 overflow-x-auto">{children}</pre>,
  table: ({ children }) => <div className="overflow-x-auto my-2"><table className="w-full text-xs border-collapse">{children}</table></div>,
  thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
  th: ({ children }) => <th className="text-left font-semibold px-2 py-1 border border-border">{children}</th>,
  td: ({ children }) => <td className="px-2 py-1 border border-border align-top">{children}</td>,
}

// Renders Markdown (GFM: tables, task lists, strikethrough) styled compact for
// chat bubbles. `className` overrides the wrapper (defaults to Hermes styling).
export default function Markdown({ content, className }: { content: string; className?: string }) {
  return (
    <div className={className ?? 'text-sm leading-relaxed break-words'}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
