import { auth } from '@clerk/nextjs/server';
import { NextResponse } from 'next/server';

/**
 * Validates if the currently authenticated user is authorized to perform
 * administrative or destructive actions.
 * 
 * It checks the Clerk userId against the AUTHORIZED_USER_ID environment variable.
 */
export async function checkAuthorization() {
  const { userId } = await auth();

  if (!userId) {
    return { 
      authorized: false, 
      response: NextResponse.json({ error: 'Unauthorized' }, { status: 401 }) 
    };
  }

  const authorizedId = process.env.AUTHORIZED_USER_ID;

  if (!authorizedId) {
    console.error('❌ SECURITY ALERT: AUTHORIZED_USER_ID is not configured in .env');
    return { 
      authorized: false, 
      response: NextResponse.json({ 
        error: 'Forbidden: Access restricted. Admin must configure AUTHORIZED_USER_ID.' 
      }, { status: 403 }) 
    };
  }

  if (userId !== authorizedId) {
    console.warn(`🚫 Unauthorized action attempt by user ${userId}`);
    return { 
      authorized: false, 
      response: NextResponse.json({ error: 'Forbidden: You do not have permission to perform this action.' }, { status: 403 }) 
    };
  }

  return { authorized: true };
}

export { isOwner } from './owner'

/**
 * Handler-level re-check of the owner gate (middleware enforces it too — this
 * keeps every route safe if the middleware matcher or a framework bug ever
 * lets a request through). Returns the error response to send, or null.
 *
 *   const denied = await requireOwner()
 *   if (denied) return denied
 */
export async function requireOwner(): Promise<NextResponse | null> {
  const result = await checkAuthorization()
  return result.authorized ? null : result.response!
}
