import { NextResponse } from 'next/server'
import { requireOwner } from '@/lib/auth'

export const dynamic = 'force-dynamic'

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://localhost:8001'

// Hardcoded pricing & metadata per model (USD per 1M tokens)
const MODEL_METADATA: Record<string, { context: string; input: number; output: number; vision?: boolean }> = {
  // OpenAI
  'gpt-4o':                    { context: '128K', input: 2.50,  output: 10.00, vision: true },
  'gpt-4o-mini':               { context: '128K', input: 0.15,  output: 0.60,  vision: true },
  'gpt-4o-mini-2024-07-18':    { context: '128K', input: 0.15,  output: 0.60,  vision: true },
  'gpt-4o-2024-11-20':         { context: '128K', input: 2.50,  output: 10.00, vision: true },
  'gpt-4-turbo':               { context: '128K', input: 10.00, output: 30.00, vision: true },
  'gpt-4':                     { context: '8K',   input: 30.00, output: 60.00 },
  'gpt-3.5-turbo':             { context: '16K',  input: 0.50,  output: 1.50 },
  'o1':                        { context: '200K', input: 15.00, output: 60.00 },
  'o1-mini':                   { context: '128K', input: 3.00,  output: 12.00 },
  'o3-mini':                   { context: '200K', input: 1.10,  output: 4.40 },
  // Gemini
  'gemini-2.0-flash':          { context: '1M',   input: 0.10,  output: 0.40,  vision: true },
  'gemini-2.0-flash-lite':     { context: '1M',   input: 0.075, output: 0.30,  vision: true },
  'gemini-2.5-flash-preview':  { context: '1M',   input: 0.15,  output: 0.60,  vision: true },
  'gemini-1.5-flash':          { context: '1M',   input: 0.075, output: 0.30,  vision: true },
  'gemini-1.5-flash-8b':       { context: '1M',   input: 0.0375,output: 0.15,  vision: true },
  'gemini-1.5-pro':            { context: '2M',   input: 1.25,  output: 5.00,  vision: true },
  'gemini-2.5-pro-preview':    { context: '2M',   input: 1.25,  output: 10.00, vision: true },
  // Perplexity
  'sonar-pro':                 { context: '200K', input: 3.00,  output: 15.00, vision: true },
  'sonar':                     { context: '128K', input: 1.00,  output: 1.00 },
  'sonar-reasoning-pro':       { context: '128K', input: 2.00,  output: 8.00 },
  'sonar-reasoning':           { context: '128K', input: 1.00,  output: 5.00 },
  'sonar-deep-research':       { context: '128K', input: 2.00,  output: 8.00 },
  // DeepSeek
  'deepseek-chat':             { context: '64K',  input: 0.27,  output: 1.10 },
  'deepseek-reasoner':         { context: '64K',  input: 0.55,  output: 2.19 },
  // MiniMax
  'MiniMax-M2.7':              { context: '128K', input: 0.40,  output: 1.60,  vision: false },
  'MiniMax-M2.7-highspeed':    { context: '128K', input: 0.20,  output: 0.80,  vision: false },
  'MiniMax-M2.5':              { context: '128K', input: 0.40,  output: 1.60,  vision: false },
  'MiniMax-M2.5-highspeed':    { context: '128K', input: 0.20,  output: 0.80,  vision: false },
  'MiniMax-Text-01':           { context: '4M',   input: 0.50,  output: 2.00 },
  'MiniMax-VL-01':             { context: '4M',   input: 0.50,  output: 2.00,  vision: true },
  // Qwen (Alibaba DashScope)
  'qwen-plus':                 { context: '128K', input: 0.80,  output: 2.00,  vision: false },
  'qwen-max':                  { context: '32K',  input: 2.40,  output: 9.60,  vision: false },
  'qwen-turbo':                { context: '128K', input: 0.30,  output: 0.90,  vision: false },
  'qwen-vl-max':               { context: '32K',  input: 3.00,  output: 12.00, vision: true },
  'qwen-vl-plus':              { context: '128K', input: 1.50,  output: 4.50,  vision: true },
}

interface ModelInfo {
  id: string
  context: string
  inputCost: number | null
  outputCost: number | null
  vision: boolean
}

async function getSettingValue(key: string): Promise<string | null> {
  try {
    const url = `${PYTHON_API_URL}/api/settings?decryptSecrets=true`
    const res = await fetch(url, { cache: 'no-store' })
    if (!res.ok) return null
    const data = await res.json()
    const all: Array<{ key: string; parsedValue: any }> = data.all ?? data.settings ?? []
    const found = all.find(s => s.key === key)
    return found ? String(found.parsedValue) : null
  } catch {
    return null
  }
}

function enrichModel(id: string): ModelInfo {
  const meta = MODEL_METADATA[id]
  return {
    id,
    context: meta?.context ?? '?',
    inputCost: meta?.input ?? null,
    outputCost: meta?.output ?? null,
    vision: meta?.vision ?? false,
  }
}

async function fetchOpenAIModels(apiKey: string): Promise<ModelInfo[]> {
  const res = await fetch('https://api.openai.com/v1/models', {
    headers: { Authorization: `Bearer ${apiKey}` },
  })
  if (!res.ok) throw new Error(`OpenAI API error: ${res.status}`)
  const data = await res.json()
  const ids: string[] = (data.data ?? [])
    .map((m: any) => m.id as string)
    .filter((id: string) => id.startsWith('gpt-') || id.startsWith('o1') || id.startsWith('o3'))
    .sort()
  return ids.map(enrichModel)
}

async function fetchGeminiModels(apiKey: string): Promise<ModelInfo[]> {
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models?key=${apiKey}`,
  )
  if (!res.ok) throw new Error(`Gemini API error: ${res.status}`)
  const data = await res.json()
  const ids: string[] = (data.models ?? [])
    .map((m: any) => (m.name as string).replace('models/', ''))
    .filter((id: string) => id.startsWith('gemini-'))
    .sort()
  return ids.map(enrichModel)
}

function getPerplexityModels(): ModelInfo[] {
  // Perplexity has no public models endpoint — use curated list
  return [
    'sonar-pro',
    'sonar',
    'sonar-reasoning-pro',
    'sonar-reasoning',
    'sonar-deep-research',
  ].map(enrichModel)
}

async function fetchDeepSeekModels(apiKey: string, baseUrl: string): Promise<ModelInfo[]> {
  const res = await fetch(`${baseUrl.replace(/\/$/, '')}/models`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  })
  if (!res.ok) throw new Error(`DeepSeek API error: ${res.status}`)
  const data = await res.json()
  const ids: string[] = (data.data ?? []).map((m: any) => m.id as string).sort()
  return ids.map(enrichModel)
}

async function fetchOpenRouterModels(apiKey: string): Promise<ModelInfo[]> {
  const res = await fetch('https://openrouter.ai/api/v1/models', {
    headers: { Authorization: `Bearer ${apiKey}` },
  })
  if (!res.ok) throw new Error(`OpenRouter API error: ${res.status}`)
  const data = await res.json()
  return (data.data ?? [])
    .map((m: any) => {
      const inputCost = m.pricing?.prompt != null ? parseFloat(m.pricing.prompt) * 1_000_000 : null
      const outputCost = m.pricing?.completion != null ? parseFloat(m.pricing.completion) * 1_000_000 : null
      const modality: string = m.architecture?.modality ?? ''
      const contextK = m.context_length ? `${Math.round(m.context_length / 1000)}K` : '?'
      return {
        id: m.id as string,
        context: contextK,
        inputCost: inputCost && inputCost > 0 ? inputCost : null,
        outputCost: outputCost && outputCost > 0 ? outputCost : null,
        vision: modality.includes('image'),
      }
    })
    .sort((a: ModelInfo, b: ModelInfo) => a.id.localeCompare(b.id))
}

async function fetchOllamaModels(ollamaUrl: string): Promise<ModelInfo[]> {
  const base = ollamaUrl.replace(/\/$/, '')
  const res = await fetch(`${base}/api/tags`)
  if (!res.ok) throw new Error(`Ollama API error: ${res.status}`)
  const data = await res.json()
  return (data.models ?? []).map((m: any) => ({
    id: m.name as string,
    context: '?',
    inputCost: null,
    outputCost: null,
    vision: false,
  }))
}

// MiniMax & Qwen are OpenAI-compatible — fetch models from /v1/models
async function fetchOpenAICompatibleModels(baseUrl: string, apiKey: string): Promise<ModelInfo[]> {
  const res = await fetch(`${baseUrl.replace(/\/$/, '')}/models`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  const data = await res.json()
  const ids: string[] = (data.data ?? []).map((m: any) => m.id as string).sort()
  return ids.map(enrichModel)
}

export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  const { searchParams } = new URL(request.url)
  const provider = searchParams.get('provider')

  if (!provider) {
    return NextResponse.json({ error: 'provider query param required' }, { status: 400 })
  }

  try {
    let models: ModelInfo[] = []

    switch (provider) {
      case 'openai': {
        const key = await getSettingValue('OPENAI_API_KEY')
        if (!key) return NextResponse.json({ error: 'OPENAI_API_KEY not set' }, { status: 400 })
        models = await fetchOpenAIModels(key)
        break
      }
      case 'gemini': {
        const key = await getSettingValue('GEMINI_API_KEY')
        if (!key) return NextResponse.json({ error: 'GEMINI_API_KEY not set' }, { status: 400 })
        models = await fetchGeminiModels(key)
        break
      }
      case 'perplexity': {
        models = getPerplexityModels()
        break
      }
      case 'deepseek': {
        const key = await getSettingValue('DEEPSEEK_API_KEY')
        const baseUrl = (await getSettingValue('DEEPSEEK_API_URL')) || 'https://api.deepseek.com'
        if (!key) return NextResponse.json({ error: 'DEEPSEEK_API_KEY not set' }, { status: 400 })
        models = await fetchDeepSeekModels(key, baseUrl)
        break
      }
      case 'openrouter': {
        const key = await getSettingValue('OPENROUTER_API_KEY')
        if (!key) return NextResponse.json({ error: 'OPENROUTER_API_KEY not set' }, { status: 400 })
        models = await fetchOpenRouterModels(key)
        break
      }
      case 'ollama': {
        const url = (await getSettingValue('OLLAMA_URL')) || 'http://localhost:11434'
        models = await fetchOllamaModels(url)
        break
      }
      case 'minimax': {
        const key = await getSettingValue('MINIMAX_API_KEY')
        const baseUrl = (await getSettingValue('MINIMAX_BASE_URL')) || 'https://api.minimax.io/v1'
        if (!key) return NextResponse.json({ error: 'MINIMAX_API_KEY not set' }, { status: 400 })
        models = await fetchOpenAICompatibleModels(baseUrl, key)
        break
      }
      case 'qwen': {
        const key = await getSettingValue('QWEN_API_KEY')
        const baseUrl = (await getSettingValue('QWEN_BASE_URL')) || 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1'
        if (!key) return NextResponse.json({ error: 'QWEN_API_KEY not set' }, { status: 400 })
        models = await fetchOpenAICompatibleModels(baseUrl, key)
        break
      }
      default:
        return NextResponse.json({ error: `Unknown provider: ${provider}` }, { status: 400 })
    }

    return NextResponse.json({ provider, models })
  } catch (err: any) {
    console.error(`[ai/models] ${provider} error:`, err)
    return NextResponse.json({ error: err.message ?? 'Failed to fetch models' }, { status: 500 })
  }
}
