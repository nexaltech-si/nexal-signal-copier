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
} from '@/lib/verification'

// Initialize DeepSeek client (OpenAI-compatible API)
const deepseek = new OpenAI({
  apiKey: process.env.DEEPSEEK_API_KEY || '',
  baseURL: 'https://api.deepseek.com',
})

export async function POST(request: Request) {
  const { authorized, response } = await checkAuthorization()
  if (!authorized) return response

  try {
    const { signalId, signalIds } = await request.json()

    // Handle batch verification
    if (signalIds && Array.isArray(signalIds)) {
      const results = await Promise.all(
        signalIds.map(async (id: string) => {
          try {
            const result = await verifySignal(id)
            return { success: true, ...result }
          } catch (error) {
            return { signalId: id, success: false, error: String(error) }
          }
        })
      )
      return NextResponse.json({ results })
    }

    // Handle single verification
    if (!signalId) {
      return NextResponse.json(
        { error: 'signalId or signalIds required' },
        { status: 400 }
      )
    }

    const result = await verifySignal(signalId)
    return NextResponse.json(result)
  } catch (error) {
    console.error('Error verifying signal:', error)
    return NextResponse.json(
      { error: 'Failed to verify signal', details: String(error) },
      { status: 500 }
    )
  }
}

async function verifySignal(signalId: string) {
  // Fetch signal from database
  const signal = await prisma.signal.findUnique({
    where: { id: signalId },
    select: {
      id: true,
      rawMessage: true,
      channelName: true,
      status: true,
      action: true,
      orderType: true,
      symbol: true,
      entryPrice: true,
      entryRangeMin: true,
      entryRangeMax: true,
      stopLoss: true,
      takeProfit: true,
      isPlan: true,
      aiVerified: true,
      aiVerificationType: true,
    },
  })

  if (!signal) {
    throw new Error('Signal not found')
  }

  // Skip if already verified
  if (signal.aiVerified) {
    return {
      signalId: signal.id,
      alreadyVerified: true,
      verificationType: signal.aiVerificationType,
      message: 'Signal already verified',
    }
  }

  // Image-only signals have no text for DeepSeek to analyze — stamp honestly
  if (!signal.rawMessage || signal.rawMessage.trim().length === 0) {
    await prisma.signal.update({
      where: { id: signalId },
      data: {
        aiVerified: true,
        aiVerifiedAt: new Date(),
        ...IMAGE_ONLY_STAMP,
      },
    })
    return {
      signalId: signal.id,
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
    temperature: 0, // Lower temperature for more consistent classification
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
  const updatedSignal = await prisma.signal.update({
    where: { id: signalId },
    data: {
      aiVerified: true,
      aiVerifiedAt: new Date(),
      aiVerificationType: verification.type,
      aiVerificationScore: verification.confidence,
      aiVerificationNotes: verification.reasoning,
    },
  })

  return {
    signalId: updatedSignal.id,
    verificationType: verification.type,
    confidence: verification.confidence,
    reasoning: verification.reasoning,
    verified: true,
  }
}

// GET endpoint to check verification status
export async function GET(request: Request) {
  const denied = await requireOwner()
  if (denied) return denied

  try {
    const { searchParams } = new URL(request.url)
    const signalId = searchParams.get('signalId')

    if (!signalId) {
      return NextResponse.json(
        { error: 'signalId required' },
        { status: 400 }
      )
    }

    const signal = await prisma.signal.findUnique({
      where: { id: signalId },
      select: {
        id: true,
        aiVerified: true,
        aiVerifiedAt: true,
        aiVerificationType: true,
        aiVerificationScore: true,
        aiVerificationNotes: true,
      },
    })

    if (!signal) {
      return NextResponse.json(
        { error: 'Signal not found' },
        { status: 404 }
      )
    }

    return NextResponse.json(signal)
  } catch (error) {
    console.error('Error checking verification status:', error)
    return NextResponse.json(
      { error: 'Failed to check verification status' },
      { status: 500 }
    )
  }
}
