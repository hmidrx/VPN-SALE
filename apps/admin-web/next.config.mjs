const nextConfig = {
  reactStrictMode: true,
  // CI runs the repository-level ESLint command before production builds.
  // Avoid invoking Next.js's deprecated duplicate lint phase during build.
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
