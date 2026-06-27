import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// Everything except Clerk's own sign-in/sign-up routes requires a session.
// Unauthenticated requests are redirected to the Clerk sign-in (account portal).
// /__clerk is Clerk's own clerk-js + Frontend API proxy path — it must be
// reachable WITHOUT a session (you need clerk-js to sign in), or the gate
// redirects it to /sign-in and clerk-js never loads (blank screen).
const isPublicRoute = createRouteMatcher([
  "/sign-in(.*)",
  "/sign-up(.*)",
  "/__clerk(.*)",
]);

export default clerkMiddleware(async (auth, req) => {
  if (!isPublicRoute(req)) {
    const { userId, redirectToSignIn } = await auth();
    if (!userId) {
      return redirectToSignIn({ returnBackUrl: req.url });
    }
  }
});

export const config = {
  matcher: [
    // Clerk proxies clerk-js through /__clerk/* by default (enabled in
    // clerkMiddleware); the middleware must run on those .js paths or they 404
    // and the app renders blank. Match it explicitly BEFORE the static-file
    // exclusion below (which would otherwise skip *.js).
    "/__clerk/(.*)",
    // Skip Next internals and static files, unless found in search params
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    // Always run for API routes
    "/(api|trpc)(.*)",
  ],
};
