import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

/** Signed-in-only surfaces: Pal (the AI assistant) and the Planner. Everything
 * else — builder, players, fixtures, about — is open; the engine API enforces
 * the same split server-side. */
const isProtected = createRouteMatcher(["/chat(.*)", "/planner(.*)"]);

export default clerkMiddleware(async (auth, req) => {
  if (isProtected(req)) await auth.protect();
});

export const config = {
  matcher: [
    // Skip Next.js internals and static assets; always run for API routes.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
