import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      { source: "/admin/teams", destination: "/admin/workspaces", permanent: false },
      { source: "/admin/infrastructure/quotas/teams", destination: "/admin/infrastructure/quotas/workspaces", permanent: false },
    ];
  },
};

export default nextConfig;
