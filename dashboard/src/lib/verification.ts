// Shared AI verification logic for /api/signals/verify and /api/signals/auto-verify

// DeepSeek model for verification — respects the configured model (e.g. deepseek-v4-flash)
export const DEEPSEEK_VERIFICATION_MODEL = process.env.DEEPSEEK_MODEL || 'deepseek-chat'

export const VERIFICATION_SYSTEM_PROMPT = `You are a classification API endpoint. Your output is parsed by a machine.

Classify Telegram trading messages into EXACTLY ONE category:
1. TRADE_SIGNAL - Legitimate trading signal with actionable info (entry, SL, TP)
2. INFO_MESSAGE - General info, market updates, educational content (not a signal)
3. REPLY - Reply/follow-up to a prior message (not a new signal)
4. WRONG_EXECUTION - Bot incorrectly parsed or executed a signal
5. UNCLEAR - Cannot determine with confidence

TRADING LOGIC:
- BUY/LONG: SL BELOW entry, TP ABOVE entry
- SELL/SHORT: SL ABOVE entry, TP BELOW entry

WRONG_EXECUTION triggers:
- Bot direction contradicts explicit BUY/SELL/LONG/SHORT in message
- SL/TP placement inconsistent with direction (BUY with SL above entry, SELL with TP above entry)
- Severe structural errors preventing parsing
- Missing mandatory fields for an OPEN action
- Complete gibberish the bot tried to execute

Do NOT classify as WRONG_EXECUTION based on price values alone. Current year is 2026.

CRITICAL — RESPOND ONLY WITH A JSON OBJECT. NO OTHER TEXT.
{
  "type": "TRADE_SIGNAL" | "INFO_MESSAGE" | "REPLY" | "WRONG_EXECUTION" | "UNCLEAR",
  "confidence": 0.0-1.0,
  "reasoning": "1-2 sentence explanation"
}`

export interface VerifiableSignal {
  rawMessage: string
  channelName: string | null
  action?: string | null
  orderType?: string | null
  symbol?: string | null
  entryPrice?: number | null
  entryRangeMin?: number | null
  entryRangeMax?: number | null
  stopLoss?: number | null
  takeProfit?: string | null
  isPlan?: boolean | null
}

export function buildVerificationUserPrompt(signal: VerifiableSignal): string {
  let prompt = `Current date is 2026-04-01. Analyze this Telegram message from channel "${signal.channelName || 'Unknown'}":\n\n${signal.rawMessage}`

  const extracted: string[] = []
  if (signal.action) extracted.push(`action=${signal.action}`)
  if (signal.orderType) extracted.push(`direction=${signal.orderType}`)
  if (signal.symbol) extracted.push(`symbol=${signal.symbol}`)
  if (signal.entryPrice != null) extracted.push(`entry=${signal.entryPrice}`)
  else if (signal.entryRangeMin != null || signal.entryRangeMax != null) {
    extracted.push(`entry_range=${signal.entryRangeMin ?? '?'}-${signal.entryRangeMax ?? '?'}`)
  }
  if (signal.stopLoss != null) extracted.push(`SL=${signal.stopLoss}`)
  if (signal.takeProfit) {
    try {
      const tps = JSON.parse(signal.takeProfit)
      if (Array.isArray(tps) && tps.length > 0) extracted.push(`TP=[${tps.join(', ')}]`)
    } catch {
      extracted.push(`TP=${signal.takeProfit}`)
    }
  }
  if (signal.isPlan) extracted.push('is_plan=true')

  if (extracted.length > 0) {
    prompt += `\n\nThe bot extracted and executed: ${extracted.join(', ')}.\nCross-check this against the message text — if the message states an explicit direction (BUY/SELL/LONG/SHORT) that contradicts the extracted direction, or the SL/TP placement is inconsistent with the extracted direction, classify as WRONG_EXECUTION.`
  }

  return prompt
}

export interface VerificationResult {
  type: string
  confidence: number
  reasoning?: string
}

export function parseVerificationResponse(responseContent: string, reasoningContent?: string): VerificationResult {
  // Build candidates in priority order: content first, then reasoning as fallback
  const candidates: string[] = [responseContent]
  if (reasoningContent && reasoningContent.trim()) {
    candidates.push(reasoningContent)
  }

  for (const raw of candidates) {
    if (!raw) continue

    // Clean the response (remove markdown code blocks)
    const clean = raw
      .replace(/```json\s*/gi, '')
      .replace(/```\s*/g, '')
      .trim()

    if (!clean) continue

    // Strategy 1: direct JSON parse
    try {
      const parsed = JSON.parse(clean)
      if (parsed.type && typeof parsed.confidence === 'number') {
        return parsed as VerificationResult
      }
    } catch {
      // Not valid JSON — try extraction
    }

    // Strategy 2: find a JSON object containing "type" and "confidence" within text
    const jsonMatch = clean.match(/\{[\s\S]*?"type"[\s\S]*?"confidence"[\s\S]*?\}/)
    if (jsonMatch) {
      try {
        const parsed = JSON.parse(jsonMatch[0])
        if (parsed.type && typeof parsed.confidence === 'number') {
          return parsed as VerificationResult
        }
      } catch {
        // Continue to next candidate
      }
    }

    // Strategy 3: any JSON object at all (last resort)
    const anyJson = clean.match(/\{[\s\S]*?\}/)
    if (anyJson) {
      try {
        const parsed = JSON.parse(anyJson[0])
        if (parsed.type && typeof parsed.confidence === 'number') {
          return parsed as VerificationResult
        }
      } catch {
        // Continue to next candidate
      }
    }
  }

  throw new Error('No valid JSON verification object found in response')
}

// Stamp applied to image-only signals where text verification is not applicable
export const IMAGE_ONLY_STAMP = {
  aiVerificationType: 'IMAGE_ONLY',
  aiVerificationScore: null,
  aiVerificationNotes: 'Image-only signal — text verification not applicable',
} as const
