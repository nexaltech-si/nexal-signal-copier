// Channel rules: shared types, the action catalogue, and a matcher that mirrors the bot's
// (src/services/channel_behavior_service.py ChannelBehaviorService.matches) so the dashboard
// tester shows exactly which rule the bot will apply.

export type PatternType = 'REGEX' | 'CONTAINS' | 'EXACT' | 'STARTS_WITH'

export type ActionType =
  | 'IGNORE'
  | 'CLOSE'
  | 'PARTIAL_CLOSE'
  | 'BREAKEVEN'
  | 'LOCK_PROFIT'
  | 'MODIFY_SL'
  | 'MODIFY_TP'
  | 'CANCEL'
  | 'AI_MANAGED'

export interface ChannelRule {
  id: string
  channelId: string
  channelTitle: string | null
  ruleName: string
  isEnabled: boolean
  priority: number
  replyPattern: string
  patternType: PatternType
  isCaseSensitive: boolean
  actionType: ActionType
  actionParams: Record<string, unknown>
  conditions: Record<string, unknown>
  matchCount: number
  successCount: number
  lastMatchedAt: string | null
  lastUsedAt: string | null
  description: string | null
  createdAt: string
  updatedAt: string
}

export type MatchableRule = Pick<ChannelRule, 'replyPattern' | 'patternType' | 'isCaseSensitive'>

export interface ParamField {
  key: string
  label: string
  placeholder: string
  required?: boolean
}

export interface ActionMeta {
  label: string
  summary: string
  tone: 'muted' | 'danger' | 'success' | 'primary' | 'warning'
  params: ParamField[]
}

export const ACTIONS: Record<ActionType, ActionMeta> = {
  IGNORE: {
    label: 'Ignore',
    summary: 'Drop the message: no AI call, no trade action.',
    tone: 'muted',
    params: [],
  },
  CLOSE: {
    label: 'Close trade',
    summary: 'Close the signal’s positions and cancel its pending orders.',
    tone: 'danger',
    params: [],
  },
  PARTIAL_CLOSE: {
    label: 'Partial close',
    summary: 'Bank part of the position.',
    tone: 'warning',
    params: [{ key: 'percentage', label: 'Close %', placeholder: '50' }],
  },
  BREAKEVEN: {
    label: 'Breakeven',
    summary: 'Move stop loss to entry. If only pending orders exist, they are cancelled.',
    tone: 'success',
    params: [],
  },
  LOCK_PROFIT: {
    label: 'Lock profit',
    summary: 'Move stop loss into profit by N pips.',
    tone: 'success',
    params: [{ key: 'pips', label: 'Pips', placeholder: '20' }],
  },
  MODIFY_SL: {
    label: 'Set stop loss',
    summary: 'Move stop loss to a price. Leave empty to use the price in the message.',
    tone: 'primary',
    params: [{ key: 'sl_price', label: 'SL price', placeholder: 'from message' }],
  },
  MODIFY_TP: {
    label: 'Set take profit',
    summary: 'Move take profit to a price. Leave empty to use the price in the message.',
    tone: 'primary',
    params: [{ key: 'tp_price', label: 'TP price', placeholder: 'from message' }],
  },
  CANCEL: {
    label: 'Cancel pending',
    summary: 'Cancel the signal’s unfilled orders.',
    tone: 'danger',
    params: [],
  },
  AI_MANAGED: {
    label: 'AI decides',
    summary: 'No fixed action: the AI acts on your note for this channel.',
    tone: 'primary',
    params: [],
  },
}

export const ACTION_TYPES = Object.keys(ACTIONS) as ActionType[]

export const PATTERN_TYPES: { value: PatternType; label: string; hint: string }[] = [
  { value: 'REGEX', label: 'Regex', hint: 'Regular expression, e.g. \\b(be|breakeven)\\b' },
  { value: 'CONTAINS', label: 'Contains', hint: 'Message contains this text' },
  { value: 'STARTS_WITH', label: 'Starts with', hint: 'Message starts with this text' },
  { value: 'EXACT', label: 'Exact', hint: 'Whole message equals this text' },
]

export const isActionType = (v: unknown): v is ActionType => typeof v === 'string' && v in ACTIONS
export const isPatternType = (v: unknown): v is PatternType =>
  PATTERN_TYPES.some((p) => p.value === v)

/** Error message for an unusable pattern, or null when it is fine. */
export function patternError(pattern: string, type: PatternType): string | null {
  if (!pattern.trim()) return 'Pattern is required'
  if (type !== 'REGEX') return null
  try {
    new RegExp(pattern)
    return null
  } catch (e) {
    return e instanceof Error ? e.message.replace(/^Invalid regular expression: /, '') : 'Invalid regex'
  }
}

/** Telegram markdown → plain text for matching. Mirrors plain_text in channel_behavior_service.py. */
export const stripMarkers = (text: string) =>
  (text || '').replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, '$1').replace(/```|\*\*|__|~~|\|\||`/g, '')

export function matchesRule(raw: string, rule: MatchableRule): boolean {
  const text = stripMarkers(raw)
  const pattern = rule.replyPattern || ''
  if (!pattern) return false
  if (rule.patternType === 'REGEX') {
    try {
      return new RegExp(pattern, rule.isCaseSensitive ? '' : 'i').test(text)
    } catch {
      return false
    }
  }
  let t = text
  let p = pattern
  if (!rule.isCaseSensitive) {
    t = t.toLowerCase()
    p = p.toLowerCase()
  }
  t = t.trim()
  p = p.trim()
  if (rule.patternType === 'CONTAINS') return t.includes(p)
  if (rule.patternType === 'EXACT') return t === p
  if (rule.patternType === 'STARTS_WITH') return t.startsWith(p)
  return false
}

/** Same order the bot checks: priority desc, then oldest first. */
export function byPriority<T extends Pick<ChannelRule, 'priority' | 'createdAt'>>(a: T, b: T) {
  return b.priority - a.priority || a.createdAt.localeCompare(b.createdAt)
}

/** The rule the bot would apply to this message in this channel (enabled only), or null. */
export function firstMatch<T extends ChannelRule>(text: string, channelId: string, rules: T[]): T | null {
  return (
    rules
      .filter((r) => r.isEnabled && r.channelId === channelId)
      .sort(byPriority)
      .find((r) => matchesRule(text, r)) ?? null
  )
}

/** "50%", "SL 4120.5", "+20 pips" — the rule's parameters in a few words. */
export function paramsSummary(actionType: ActionType, params: Record<string, unknown>): string | null {
  const v = (k: string) => (params[k] === undefined || params[k] === null || params[k] === '' ? null : params[k])
  switch (actionType) {
    case 'PARTIAL_CLOSE':
      return `${v('percentage') ?? 50}%`
    case 'LOCK_PROFIT':
      return `+${v('pips') ?? 20} pips`
    case 'MODIFY_SL':
      return v('sl_price') ? `SL ${v('sl_price')}` : 'SL from message'
    case 'MODIFY_TP':
      return v('tp_price') ? `TP ${v('tp_price')}` : 'TP from message'
    default:
      return null
  }
}

/** Keep only the parameters the action uses, as numbers. */
export function cleanParams(actionType: ActionType, raw: Record<string, unknown>): Record<string, number> {
  const out: Record<string, number> = {}
  for (const f of ACTIONS[actionType].params) {
    const n = Number(raw[f.key])
    if (raw[f.key] !== '' && raw[f.key] !== undefined && raw[f.key] !== null && Number.isFinite(n)) out[f.key] = n
  }
  return out
}

/** Rule suggestion from a learned message pattern ({number}/{price} placeholders). */
export function patternToRegex(pattern: string): string {
  // Learned patterns are cut at 200 chars + "..." (sometimes mid-marker); match on the kept part
  return stripMarkers(pattern.replace(/[*_~|`]*\.\.\.$/, '')).trim()
    .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    .replace(/\\\{number\\\}/g, '\\d+')
    .replace(/\\\{price\\\}/g, '\\d+(?:\\.\\d+)?')
}

/** The learning tracker tags messages CLOSE/MODIFY; map that onto a rule action. */
export function suggestedAction(learned: string | null): ActionType {
  if (learned === 'CLOSE') return 'CLOSE'
  return 'AI_MANAGED'
}

export interface RuleInput {
  channelId?: string
  channelTitle?: string | null
  ruleName?: string
  isEnabled?: boolean
  priority?: number
  replyPattern?: string
  patternType?: PatternType
  isCaseSensitive?: boolean
  actionType?: ActionType
  actionParams?: Record<string, unknown>
  conditions?: Record<string, unknown>
  description?: string | null
}

/**
 * Validate a create (full) or update (partial) body into DB columns.
 * Returns { error } on bad input so the bot never loads a rule it cannot use.
 */
export function ruleDataFromInput(
  body: RuleInput,
  partial: boolean,
  current?: { replyPattern: string; patternType: string; actionType: string },
): { data: Record<string, unknown> } | { error: string } {
  const data: Record<string, unknown> = {}
  const has = (k: keyof RuleInput) => body[k] !== undefined

  if (!partial || has('channelId')) {
    if (!body.channelId?.trim()) return { error: 'Choose a channel' }
    data.channelId = body.channelId.trim()
  }
  if (has('channelTitle')) data.channelTitle = body.channelTitle || null
  if (!partial || has('ruleName')) {
    if (!body.ruleName?.trim()) return { error: 'Give the rule a name' }
    data.ruleName = body.ruleName.trim()
  }
  if (!partial || has('actionType')) {
    if (!isActionType(body.actionType)) return { error: 'Choose a valid action' }
    data.actionType = body.actionType
  }
  if (!partial || has('patternType')) {
    if (!isPatternType(body.patternType ?? 'REGEX')) return { error: 'Choose a valid pattern type' }
    data.patternType = body.patternType ?? 'REGEX'
  }
  if (!partial || has('replyPattern') || has('patternType')) {
    const pattern = body.replyPattern ?? current?.replyPattern ?? ''
    const err = patternError(pattern, (data.patternType ?? current?.patternType ?? 'REGEX') as PatternType)
    if (err) return { error: `Pattern: ${err}` }
    data.replyPattern = pattern
  }
  if (!partial || has('actionParams') || has('actionType')) {
    const action = (data.actionType ?? current?.actionType) as ActionType
    const params = cleanParams(action, body.actionParams ?? {})
    if (action === 'PARTIAL_CLOSE' && params.percentage !== undefined && !(params.percentage > 0 && params.percentage <= 100)) {
      return { error: 'Close % must be between 1 and 100' }
    }
    data.actionParams = Object.keys(params).length ? JSON.stringify(params) : null
  }
  if (has('conditions')) {
    const c = body.conditions
    if (c !== null && (typeof c !== 'object' || Array.isArray(c))) return { error: 'Conditions must be a JSON object' }
    data.conditions = c && Object.keys(c).length ? JSON.stringify(c) : null
  }
  if (!partial || has('priority')) {
    const p = Math.round(Number(body.priority ?? 0))
    if (!Number.isFinite(p)) return { error: 'Priority must be a number' }
    data.priority = Math.max(0, Math.min(100, p))
  }
  if (!partial || has('isCaseSensitive')) data.isCaseSensitive = !!body.isCaseSensitive
  if (!partial || has('isEnabled')) data.isEnabled = body.isEnabled ?? true
  if (!partial || has('description')) data.description = body.description?.trim() || null
  return { data }
}

/** DB row (JSON columns as strings) → API shape. */
export function serializeRule(r: {
  id: string; channelId: string; channelTitle: string | null; ruleName: string; isEnabled: boolean
  priority: number; replyPattern: string; patternType: string; isCaseSensitive: boolean; actionType: string
  actionParams: string | null; conditions: string | null; matchCount: number; successCount: number
  lastMatchedAt: Date | null; lastUsedAt: Date | null; description: string | null; createdAt: Date; updatedAt: Date
}, title?: string | null): ChannelRule {
  const json = (s: string | null) => {
    try {
      const v = s ? JSON.parse(s) : {}
      return v && typeof v === 'object' && !Array.isArray(v) ? v : {}
    } catch {
      return {}
    }
  }
  return {
    ...r,
    channelTitle: title ?? r.channelTitle,
    patternType: r.patternType as PatternType,
    actionType: r.actionType as ActionType,
    actionParams: json(r.actionParams),
    conditions: json(r.conditions),
    lastMatchedAt: r.lastMatchedAt?.toISOString() ?? null,
    lastUsedAt: r.lastUsedAt?.toISOString() ?? null,
    createdAt: r.createdAt.toISOString(),
    updatedAt: r.updatedAt.toISOString(),
  }
}
