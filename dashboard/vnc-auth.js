'use strict';

// Owner check for the /vnc-proxy routes in server.js (audit finding H-03).
//
// Those routes bypass Next.js and its Clerk middleware entirely, so the custom
// server has to authenticate them itself. The previous check only looked for a
// cookie *named* __session, which anyone can forge. This verifies the Clerk
// session JWT (signature, expiry, authorized party) and requires the subject to
// be AUTHORIZED_USER_ID — the same rule the middleware applies to every page.

const { verifyToken } = require('@clerk/backend');

// Clerk rotates the __session JWT about once a minute while the dashboard tab
// is open; a little slack keeps VNC asset loads from failing at the boundary.
const CLOCK_SKEW_MS = 30_000;

function parseCookies(header) {
  const out = {};
  for (const part of (header || '').split(';')) {
    const idx = part.indexOf('=');
    if (idx < 0) continue;
    const name = part.slice(0, idx).trim();
    if (!name || name in out) continue;
    try {
      out[name] = decodeURIComponent(part.slice(idx + 1).trim());
    } catch {
      out[name] = part.slice(idx + 1).trim();
    }
  }
  return out;
}

/** The Clerk session JWT: `__session`, or a suffixed `__session_<hash>` variant. */
function sessionTokenFromCookies(header) {
  const cookies = parseCookies(header);
  if (cookies.__session) return cookies.__session;
  const suffixed = Object.keys(cookies).find((k) => k.startsWith('__session_'));
  return suffixed ? cookies[suffixed] : null;
}

function authorizedParties(env) {
  const domain = (env.DASHBOARD_DOMAIN || '').trim();
  return domain ? [`https://${domain}`] : undefined;
}

/**
 * Resolves true only for a valid, unexpired session belonging to the owner.
 * Never throws. `verify` is injectable for tests.
 */
async function isOwnerRequest(req, { env = process.env, verify = verifyToken } = {}) {
  const ownerId = env.AUTHORIZED_USER_ID;
  if (!ownerId) return false; // fail closed, same as the middleware

  const token = sessionTokenFromCookies(req.headers && req.headers.cookie);
  if (!token) return false;

  try {
    const payload = await verify(token, {
      secretKey: env.CLERK_SECRET_KEY,
      jwtKey: env.CLERK_JWT_KEY || undefined,
      authorizedParties: authorizedParties(env),
      clockSkewInMs: CLOCK_SKEW_MS,
    });
    return Boolean(payload && payload.sub === ownerId);
  } catch {
    return false;
  }
}

module.exports = { isOwnerRequest, sessionTokenFromCookies, parseCookies };
