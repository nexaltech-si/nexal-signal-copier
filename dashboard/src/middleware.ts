import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";
import { isOwner } from "@/lib/owner";

// /api/ea/signals, /api/ea/mirror and /api/ea/report are reached by MT5 EAs,
// which cannot complete a Clerk browser sign-in — they authenticate via their
// own X-EA-Key check instead (see each route's handler). Keep this list to exactly the paths that do their
// own auth; anything else added here skips Clerk with no replacement check.
const isPublicRoute = createRouteMatcher(['/sign-in(.*)', '/sign-up(.*)', '/manifest.json', '/api/ea/signals', '/api/ea/mirror', '/api/ea/report']);
const isApiRoute = createRouteMatcher(['/api(.*)', '/trpc(.*)']);

export default clerkMiddleware(async (auth, request) => {
  if (isPublicRoute(request)) return;

  const session = await auth();
  if (!session?.userId) {
    if (isApiRoute(request)) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }
    return NextResponse.redirect(new URL('/sign-in', request.url));
  }

  // Single-owner app: being signed in to the Clerk instance is not enough.
  // Every page and API route controls the live trading account or exposes
  // decrypted secrets, so only AUTHORIZED_USER_ID gets through (audit H-04).
  if (!isOwner(session.userId)) {
    console.warn(`🚫 Non-owner Clerk user ${session.userId} blocked on ${request.nextUrl.pathname}`);
    if (isApiRoute(request)) {
      return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
    }
    return new NextResponse('Forbidden — this dashboard is restricted to its owner.', {
      status: 403,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }
});

export const config = {
  matcher: [
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    '/(api|trpc)(.*)',
  ],
};
