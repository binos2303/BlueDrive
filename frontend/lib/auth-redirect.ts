const FALLBACK_PATH = "/drive";

export function authFormHref(mode: "login" | "register", candidate?: string | null): string {
  return `/${mode}?${new URLSearchParams({ next: safeInternalRedirect(candidate) })}`;
}

export function safeInternalRedirect(
  candidate: string | null | undefined,
  fallback = FALLBACK_PATH,
): string {
  if (
    !candidate ||
    !candidate.startsWith("/") ||
    candidate.startsWith("//") ||
    candidate.includes("\\") ||
    /%(?:2f|5c)/i.test(candidate) ||
    /[\u0000-\u001f\u007f]/.test(candidate)
  ) {
    return fallback;
  }

  try {
    const destination = new URL(candidate, "https://securedrive.invalid");
    if (destination.origin !== "https://securedrive.invalid") return fallback;
    if (destination.pathname === "/login" || destination.pathname === "/register") {
      return fallback;
    }
    // Đăng nhập lại yêu cầu mở invitation gốc; không mang credential vào query `next`.
    const invitationPath = decodeURIComponent(destination.pathname).replace(/\/+$/, "");
    if (["/workspace-invite", "/admin-invite", "/organization-invite"].includes(invitationPath)) {
      return invitationPath;
    }
    return `${destination.pathname}${destination.search}${destination.hash}`;
  } catch {
    return fallback;
  }
}
