import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const token = request.cookies.get("admin_token")?.value;
  const { pathname } = request.nextUrl;

  // Guard all administrative dashboards and the editorial newsroom
  if (pathname.startsWith("/admin") || pathname.startsWith("/newsroom")) {
    if (!token) {
      // Redirect unauthorized users back to corporate login portal
      const loginUrl = new URL("/login", request.url);
      return NextResponse.redirect(loginUrl);
    }
  }

  return NextResponse.next();
}

// Intercept administrative routes
export const config = {
  matcher: ["/admin/:path*", "/newsroom", "/newsroom/:path*"],
};
