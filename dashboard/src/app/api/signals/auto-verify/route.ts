import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { checkAuthorization, requireOwner } from '@/lib/auth'
import OpenAI from 'openai'
import {
  VERIFICATION_SYSTEM_PROMPT,
  buildVerificationUserPrompt,
  parseVerificationResponse,
  IMAGE_ONLY_STAMP,
  DEEPSEEK_VERIFICATION_MODEL,
  type VerifiableSignal,
} from '@/lib/verification'

// Initialize DeepSeek client (OpenAI-compatible API)
const deepseek = new OpenAI({
  apiKey: process.env.DEEPSEEK_API_KEY || '',
  baseURL: 'https://api.deepseek.com',
})

type UnverifiedSignal = VerifiableSignal & { id: string }

/**
 * POST /api/signals/auto-verify
 * Automatically verify all unverified signals
 * Can be called manually or via cron job
 */
export async function POST(request: Request) {
  const { authorized, response } = await checkAuthorization()
  if (!authorized) return response

  try {
    const { limit = 10 } = await request.json().catch(() => ({}))

    // Check if auto-verification is enabled
    const autoVerifyEnabled = process.env.AI_AUTO_VERIFICATION_ENABLED === 'true'

    if (!autoVerifyEnabled) {
      return NextResponse.json({
        success: false,
        message: 'Auto-verification is disabled',
        verified: 0
      })
    }

    // Find unverified signals (most recent first)
    const unverifiedSignals = await prisma.signal.findMany({
      where: {
        aiVerified: false,
      },
      orderBy: {
        createdAt: 'desc',
      },
      take: limit,
      select: {
        id: true,
        rawMessage: true,
        channelName: true,
        action: true,
        orderType: true,
        symbol: true,
        entryPrice: true,
        entryRangeMin: true,
        entryRangeMax: true,
        stopLoss: true,
        takeProfit: true,
        isPlan: true,
        createdAt: true,
      },
    })

    if (unverifiedSignals.length === 0) {
      return NextResponse.json({
        success: true,
        message: 'No unverified signals found',
        verified: 0
      })
    }

    // Verify each signal
    const results = []
    for (const signal of unverifiedSignals) {
      try {
        const result = await verifySignal(signal)
        results.push({ signalId: signal.id, success: true, ...result })
      } catch (error) {
        results.push({
          signalId: signal.id,
          success: false,
          error: String(error)
        })
      }
    }

    const successCount = results.filter(r => r.success).length

    return NextResponse.json({
      success: true,
      message: `Verified ${successCount} of ${unverifiedSignals.length} signals`,
      verified: successCount,
      total: unverifiedSignals.length,
      results
    })

  } catch (error) {
    console.error('Error in auto-verify:', error)
    return NextResponse.json(
      { error: 'Failed to auto-verify signals', details: String(error) },
      { status: 500 }
    )
  }
}

/**
 * GET /api/signals/auto-verify
 * Check status and get count of unverified signals
 */
export async function GET() {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const autoVerifyEnabled = process.env.AI_AUTO_VERIFICATION_ENABLED === 'true'

    const unverifiedCount = await prisma.signal.count({
      where: {
        aiVerified: false,
      },
    })

    return NextResponse.json({
      enabled: autoVerifyEnabled,
      unverifiedCount,
      message: autoVerifyEnabled
        ? `Auto-verification enabled. ${unverifiedCount} signals pending.`
        : 'Auto-verification disabled'
    })
  } catch (error) {
    console.error('Error checking auto-verify status:', error)
    return NextResponse.json(
      { error: 'Failed to check status' },
      { status: 500 }
    )
  }
}

async function verifySignal(signal: UnverifiedSignal) {
  // Image-only signals have no text for DeepSeek to analyze — stamp honestly
  if (!signal.rawMessage || signal.rawMessage.trim().length === 0) {
    await prisma.signal.update({
      where: { id: signal.id },
      data: {
        aiVerified: true,
        aiVerifiedAt: new Date(),
        ...IMAGE_ONLY_STAMP,
      },
    })
    return {
      verificationType: IMAGE_ONLY_STAMP.aiVerificationType,
      confidence: null,
      reasoning: IMAGE_ONLY_STAMP.aiVerificationNotes,
    }
  }

  // Call DeepSeek API for verification, cross-checking the extracted signal
  const completion = await deepseek.chat.completions.create({
    model: DEEPSEEK_VERIFICATION_MODEL,
    messages: [
      { role: 'system', content: VERIFICATION_SYSTEM_PROMPT },
      { role: 'user', content: buildVerificationUserPrompt(signal) },
    ],
    temperature: 0,
    max_tokens: 800,
  })

  const msg = completion.choices[0]?.message
  const responseContent = msg?.content?.trim() || ''
  const reasoningContent = (msg as unknown as { reasoning_content?: string })?.reasoning_content?.trim() || ''

  let verification
  try {
    verification = parseVerificationResponse(responseContent, reasoningContent)
  } catch {
    console.error('Failed to parse AI response:', responseContent || reasoningContent)
    throw new Error('Invalid AI response format')
  }

  // Update signal in database
  await prisma.signal.update({
    where: { id: signal.id },
    data: {
      aiVerified: true,
      aiVerifiedAt: new Date(),
      aiVerificationType: verification.type,
      aiVerificationScore: verification.confidence,
      aiVerificationNotes: verification.reasoning,
    },
  })

  return {
    verificationType: verification.type,
    confidence: verification.confidence,
    reasoning: verification.reasoning,
  }
}
