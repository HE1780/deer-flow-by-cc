// frontend/middleware.ts
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Default cookie name — override with NEXT_PUBLIC_DEERFLOW_COOKIE_NAME if backend
// is configured with DEERFLOW_COOKIE_NAME=<custom>.
const COOKIE_NAME =
  process.env.NEXT_PUBLIC_DEERFLOW_COOKIE_NAME ?? "deerflow_session";

export function middleware(req: NextRequest) {
  const session = req.cookies.get(COOKIE_NAME);
  if (session?.value) {
    return NextResponse.next();
  }

  const url = req.nextUrl.clone();
  const next = req.nextUrl.pathname + req.nextUrl.search;
  url.pathname = "/login";
  url.search = `?next=${encodeURIComponent(next)}`;
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/admin", "/admin/:path*", "/workspace", "/workspace/:path*"],
};
