import type { NextConfig } from "next";

/**
 * Locus is a client-rendered application that Next serves.
 *
 * Every route is a client component: the session is a JWT held in
 * `localStorage`/`sessionStorage`, the chat streams over SSE, and inference is
 * reached at `MOE_BASE_URL` on the backend's own loopback interface. There is
 * no server-side data fetching to do here, so nothing is prerendered against a
 * backend the build machine cannot reach.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,

  // The API lives in a separate FastAPI process, so it is addressed absolutely
  // rather than proxied. `NEXT_PUBLIC_` is required: this is read in the
  // browser, and an unprefixed variable is stripped from the client bundle.
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
