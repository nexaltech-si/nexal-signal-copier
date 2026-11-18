import { NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { checkAuthorization } from '@/lib/auth'

export async function POST() {
  const { authorized, response } = await checkAuthorization()
  if (!authorized) return response

  try {
    // Delete in the correct order to respect foreign key constraints
    
    // 1. Delete trade actions first (references trades)
    const deletedActions = await prisma.tradeAction.deleteMany()
    
    // 2. Delete message mappings
    const deletedMessages = await prisma.messageMapping.deleteMany()
    
    // 3. Delete all trades (this includes child trades)
    const deletedTrades = await prisma.trade.deleteMany()
    
    // 4. Delete all signals
    const deletedSignals = await prisma.signal.deleteMany()

    return NextResponse.json({
      success: true,
      deletedSignals: deletedSignals.count,
      deletedTrades: deletedTrades.count,
      deletedActions: deletedActions.count,
      deletedMessages: deletedMessages.count,
      message: 'Database cleaned successfully'
    })
  } catch (error) {
    console.error('Error cleaning database:', error)
    return NextResponse.json(
      { 
        error: 'Failed to clean database',
        details: error instanceof Error ? error.message : 'Unknown error'
      },
      { status: 500 }
    )
  }
}
