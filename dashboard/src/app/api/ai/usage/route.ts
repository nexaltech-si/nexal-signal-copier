import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

// ─── Pricing per 1M tokens (USD) ─────────────────────────────────────────────
const PRICING: Record<string, { input: number; output: number }> = {
  // OpenAI
  'gpt-4o':                 { input: 2.50,  output: 10.00 },
  'gpt-4o-mini':            { input: 0.15,  output: 0.60  },
  'gpt-4-turbo':            { input: 10.00, output: 30.00 },
  'gpt-4':                  { input: 30.00, output: 60.00 },
  'gpt-3.5-turbo':          { input: 0.50,  output: 1.50  },
  'o1':                     { input: 15.00, output: 60.00 },
  'o1-mini':                { input: 3.00,  output: 12.00 },
  'o3-mini':                { input: 1.10,  output: 4.40  },
  // Gemini
  'gemini-2.0-flash':       { input: 0.10,  output: 0.40  },
  'gemini-2.0-flash-lite':  { input: 0.075, output: 0.30  },
  'gemini-1.5-flash':       { input: 0.075, output: 0.30  },
  'gemini-1.5-pro':         { input: 1.25,  output: 5.00  },
  // Perplexity
  'sonar-pro':              { input: 3.00,  output: 15.00 },
  'sonar':                  { input: 1.00,  output: 1.00  },
  'sonar-reasoning-pro':    { input: 2.00,  output: 8.00  },
  'sonar-reasoning':        { input: 1.00,  output: 5.00  },
  // DeepSeek
  'deepseek-chat':          { input: 0.27,  output: 1.10  },
  'deepseek-reasoner':      { input: 0.55,  output: 2.19  },
}

function estimateCost(model: string, inputTokens: number, outputTokens: number): number {
  // Try exact match first, then prefix match
  const key = Object.keys(PRICING).find(k => model.startsWith(k)) ?? model
  const p = PRICING[key]
  if (!p) return 0
  return (inputTokens / 1_000_000) * p.input + (outputTokens / 1_000_000) * p.output
}

async function getAllSettings(): Promise<Record<string, string>> {
  try {
    const res = await fetch(`${PYTHON_API_URL}/api/settings?decryptSecrets=true`, { cache: 'no-store' })
    if (!res.ok) return {}
    const data = await res.json()
    const all: Array<{ key: string; parsedValue: any }> = data.all ?? data.settings ?? []
    return Object.fromEntries(all.map(s => [s.key, String(s.parsedValue ?? '')]))
  } catch {
    return {}
  }
}

// ─── OpenAI ───────────────────────────────────────────────────────────────────
async function fetchOpenAIUsage(apiKey: string, startDate: string, endDate: string) {
  const start = Math.floor(new Date(startDate).getTime() / 1000)
  const end = Math.floor(new Date(endDate + 'T23:59:59Z').getTime() / 1000)

  // Try new admin endpoint first (works with project keys)
  try {
    const res = await fetch(
      `https://api.openai.com/v1/organization/usage/completions?start_time=${start}&end_time=${end}&bucket_width=1d&limit=30`,
      { headers: { Authorization: `Bearer ${apiKey}` } }
    )
    if (res.ok) {
      const data = await res.json()
      const buckets: any[] = data.data ?? []
      const byModel: Record<string, { inputTokens: number; outputTokens: number; requests: number; cost: number }> = {}
      let totalInput = 0, totalOutput = 0, totalRequests = 0

      for (const bucket of buckets) {
        for (const result of bucket.results ?? []) {
          const model = result.model ?? 'unknown'
          const inp = result.input_tokens ?? 0
          const out = result.output_tokens ?? 0
          const req = result.num_model_requests ?? 0
          if (!byModel[model]) byModel[model] = { inputTokens: 0, outputTokens: 0, requests: 0, cost: 0 }
          byModel[model].inputTokens += inp
          byModel[model].outputTokens += out
          byModel[model].requests += req
          byModel[model].cost += estimateCost(model, inp, out)
          totalInput += inp
          totalOutput += out
          totalRequests += req
        }
      }

      const totalCost = Object.values(byModel).reduce((s, m) => s + m.cost, 0)
      return {
        provider: 'openai',
        supported: true,
        totalInputTokens: totalInput,
        totalOutputTokens: totalOutput,
        totalRequests,
        totalCost,
        byModel,
        balance: null,
        error: null,
      }
    }
  } catch {}

  // Fallback: legacy daily usage endpoint
  try {
    const days = getDaysInRange(startDate, endDate)
    const byModel: Record<string, { inputTokens: number; outputTokens: number; requests: number; cost: number }> = {}
    let totalInput = 0, totalOutput = 0, totalRequests = 0

    for (const day of days) {
      const res = await fetch(
        `https://api.openai.com/v1/usage?date=${day}`,
        { headers: { Authorization: `Bearer ${apiKey}` } }
      )
      if (!res.ok) continue
      const data = await res.json()
      for (const item of data.data ?? []) {
        const model = item.snapshot_id ?? 'unknown'
        const inp = item.n_context_tokens_total ?? 0
        const out = item.n_generated_tokens_total ?? 0
        const req = item.n_requests ?? 0
        if (!byModel[model]) byModel[model] = { inputTokens: 0, outputTokens: 0, requests: 0, cost: 0 }
        byModel[model].inputTokens += inp
        byModel[model].outputTokens += out
        byModel[model].requests += req
        byModel[model].cost += estimateCost(model, inp, out)
        totalInput += inp
        totalOutput += out
        totalRequests += req
      }
    }

    const totalCost = Object.values(byModel).reduce((s, m) => s + m.cost, 0)
    return { provider: 'openai', supported: true, totalInputTokens: totalInput, totalOutputTokens: totalOutput, totalRequests, totalCost, byModel, balance: null, error: null }
  } catch (err: any) {
    return { provider: 'openai', supported: true, error: err.message, totalInputTokens: 0, totalOutputTokens: 0, totalRequests: 0, totalCost: 0, byModel: {}, balance: null }
  }
}

// ─── OpenRouter ───────────────────────────────────────────────────────────────
async function fetchOpenRouterUsage(apiKey: string) {
  try {
    const res = await fetch('https://openrouter.ai/api/v1/auth/key', {
      headers: { Authorization: `Bearer ${apiKey}` },
    })
    if (!res.ok) throw new Error(`OpenRouter: ${res.status}`)
    const data = await res.json()
    const info = data.data ?? {}
    return {
      provider: 'openrouter',
      supported: true,
      totalCost: info.usage ?? 0,
      balance: info.limit !== null ? (info.limit ?? 0) - (info.usage ?? 0) : null,
      creditLimit: info.limit ?? null,
      isFreeTier: info.is_free_tier ?? false,
      totalInputTokens: 0,
      totalOutputTokens: 0,
      totalRequests: 0,
      byModel: {},
      error: null,
    }
  } catch (err: any) {
    return { provider: 'openrouter', supported: true, error: err.message, totalCost: 0, balance: null, totalInputTokens: 0, totalOutputTokens: 0, totalRequests: 0, byModel: {} }
  }
}

// ─── DeepSeek ─────────────────────────────────────────────────────────────────
async function fetchDeepSeekUsage(apiKey: string, baseUrl: string) {
  try {
    const base = baseUrl.replace(/\/+$/, '').replace('/v1', '')
    const res = await fetch(`${base}/user/balance`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    })
    if (!res.ok) throw new Error(`DeepSeek: ${res.status}`)
    const data = await res.json()
    const infos: any[] = data.balance_infos ?? []
    const cny = infos.find(i => i.currency === 'CNY') ?? infos[0]
    return {
      provider: 'deepseek',
      supported: true,
      balance: cny ? parseFloat(cny.total_balance) : null,
      currency: cny?.currency ?? 'CNY',
      grantedBalance: cny ? parseFloat(cny.granted_balance) : null,
      toppedUpBalance: cny ? parseFloat(cny.topped_up_balance) : null,
      isAvailable: data.is_available ?? true,
      totalCost: 0,
      totalInputTokens: 0,
      totalOutputTokens: 0,
      totalRequests: 0,
      byModel: {},
      error: null,
    }
  } catch (err: any) {
    return { provider: 'deepseek', supported: true, error: err.message, balance: null, totalCost: 0, totalInputTokens: 0, totalOutputTokens: 0, totalRequests: 0, byModel: {} }
  }
}

// ─── Perplexity ───────────────────────────────────────────────────────────────
function perplexityNoApi() {
  return { provider: 'perplexity', supported: false, reason: 'No public usage API — check perplexity.ai/settings/api', totalCost: 0, totalInputTokens: 0, totalOutputTokens: 0, totalRequests: 0, byModel: {}, balance: null, error: null }
}

// ─── Gemini ───────────────────────────────────────────────────────────────────
function geminiNoApi() {
  return { provider: 'gemini', supported: false, reason: 'Usage tracked via Google Cloud Console — no direct API key access', totalCost: 0, totalInputTokens: 0, totalOutputTokens: 0, totalRequests: 0, byModel: {}, balance: null, error: null }
}

// ─── Ollama ───────────────────────────────────────────────────────────────────
function ollamaLocal() {
  return { provider: 'ollama', supported: false, reason: 'Local model — no API cost or usage tracking', totalCost: 0, totalInputTokens: 0, totalOutputTokens: 0, totalRequests: 0, byModel: {}, balance: null, error: null }
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
function getDaysInRange(start: string, end: string): string[] {
  const days: string[] = []
  const cur = new Date(start)
  const last = new Date(end)
  while (cur <= last && days.length < 31) {
    days.push(cur.toISOString().slice(0, 10))
    cur.setDate(cur.getDate() + 1)
  }
  return days
}

// ─── Route ────────────────────────────────────────────────────────────────────
export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  const { searchParams } = new URL(request.url)
  const today = new Date().toISOString().slice(0, 10)
  const startDate = searchParams.get('start') ?? today
  const endDate = searchParams.get('end') ?? today
  const providerFilter = searchParams.get('provider')

  const settings = await getAllSettings()

  const tasks: Promise<any>[] = []

  const include = (p: string) => !providerFilter || providerFilter === p

  if (include('openai') && settings['OPENAI_API_KEY']) {
    tasks.push(fetchOpenAIUsage(settings['OPENAI_API_KEY'], startDate, endDate))
  } else if (include('openai')) {
    tasks.push(Promise.resolve({ provider: 'openai', supported: true, error: 'API key not configured', totalCost: 0, totalInputTokens: 0, totalOutputTokens: 0, totalRequests: 0, byModel: {}, balance: null }))
  }

  if (include('openrouter') && settings['OPENROUTER_API_KEY']) {
    tasks.push(fetchOpenRouterUsage(settings['OPENROUTER_API_KEY']))
  } else if (include('openrouter')) {
    tasks.push(Promise.resolve({ provider: 'openrouter', supported: true, error: 'API key not configured', totalCost: 0, balance: null, totalInputTokens: 0, totalOutputTokens: 0, totalRequests: 0, byModel: {} }))
  }

  if (include('deepseek') && settings['DEEPSEEK_API_KEY']) {
    tasks.push(fetchDeepSeekUsage(settings['DEEPSEEK_API_KEY'], settings['DEEPSEEK_API_URL'] ?? 'https://api.deepseek.com/v1'))
  } else if (include('deepseek')) {
    tasks.push(Promise.resolve({ provider: 'deepseek', supported: true, error: 'API key not configured', balance: null, totalCost: 0, totalInputTokens: 0, totalOutputTokens: 0, totalRequests: 0, byModel: {} }))
  }

  if (include('perplexity')) tasks.push(Promise.resolve(perplexityNoApi()))
  if (include('gemini')) tasks.push(Promise.resolve(geminiNoApi()))
  if (include('ollama')) tasks.push(Promise.resolve(ollamaLocal()))

  const results = await Promise.allSettled(tasks)
  const providers = results.map(r => r.status === 'fulfilled' ? r.value : { error: (r as any).reason?.message })

  const totalCost = providers.reduce((s: number, p: any) => s + (p.totalCost ?? 0), 0)

  return NextResponse.json({ startDate, endDate, totalCost, providers })
}
