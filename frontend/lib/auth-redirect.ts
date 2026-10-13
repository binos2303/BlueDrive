const FALLBACK_PATH = "/drive";

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
    return `${destination.pathname}${destination.search}${destination.hash}`;
  } catch {
    return fallback;
  }
}
