/** @type {import('next').NextConfig} */
const nextConfig = {
  // Enable standalone output for production Docker image
  output: "standalone",

  // Lint runs as its own (non-blocking) CI step. Keep it out of the
  // production build so pre-existing findings cannot break a release.
  eslint: {
    ignoreDuringBuilds: true,
  },

  // API proxy — route /api/* to the FastAPI backend
  async rewrites() {
    // Server-side proxy target. Inside Docker the browser-facing
    // NEXT_PUBLIC_API_URL (localhost) is NOT reachable from the Next server
    // process, so prefer INTERNAL_API_URL (e.g. http://backend:8000).
    const internalApi =
      process.env.INTERNAL_API_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${internalApi}/api/:path*`,
      },
    ];
  },

  // Allow external image sources (news article thumbnails)
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**" },
    ],
  },
};

module.exports = nextConfig;
