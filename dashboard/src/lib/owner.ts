/**
 * Pure owner check shared by middleware, route handlers and server.js tests.
 * Kept free of imports so it runs in the edge middleware and under plain Node.
 * Fails closed when AUTHORIZED_USER_ID is not configured.
 */
export function isOwner(userId: string | null | undefined, ownerId = process.env.AUTHORIZED_USER_ID): boolean {
  return Boolean(userId && ownerId && userId === ownerId)
}
