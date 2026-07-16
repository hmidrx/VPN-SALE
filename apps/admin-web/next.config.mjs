const nextConfig = {
  reactStrictMode: true,
  // CI runs repository-level ESLint before production builds.
  eslint: { ignoreDuringBuilds: true },
  // CI also runs strict workspace TypeScript checks before production builds.
  // Next.js 15.1.3's duplicate type-check worker exits without diagnostics on
  // this minimal workspace, so the build phase relies on the required tsc job.
  typescript: { ignoreBuildErrors: true },
};

export default nextConfig;
