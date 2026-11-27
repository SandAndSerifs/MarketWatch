import type { NextConfig } from "next";

// "same-origin" mode (used for Cloudflare Tunnel / remote access): the browser calls /api/* on the
// same host and Next.js forwards those requests to the backend, so only one port is exposed.
const sameOrigin = process.env.NEXT_PUBLIC_API_URL === "same-origin";
const backend = (process.env.MARKETPILOT_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  agentRules: false,
  async rewrites() {
    return sameOrigin ? [{ source: "/api/:path*", destination: `${backend}/api/:path*` }] : [];
  },
};

export default nextConfig;
