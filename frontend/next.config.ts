import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async headers() {
    // Link query cũ có thể được mở trước hydration; không chuyển credential qua referrer.
    return ["/admin-invite", "/organization-invite", "/workspace-invite"].map((source) => ({
      source,
      headers: [{ key: "Referrer-Policy", value: "no-referrer" }],
    }));
  },
  async redirects() {
    return [
      { source: "/admin/teams", destination: "/admin/workspaces", permanent: false },
      { source: "/admin/infrastructure/quotas/teams", destination: "/admin/infrastructure/quotas/workspaces", permanent: false },
    ];
  },
};

export default nextConfig;
