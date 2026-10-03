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
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/:path*`,
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
