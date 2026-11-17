const GIB = 1024 ** 3;

/** Quota cấp mới luôn hữu hạn; 0 giữ uploads bị chặn cho đến khi được cấp dung lượng. */
export function finiteQuotaBytes(value: string): number {
  if (!/^\d+$/.test(value.trim())) throw new Error("Enter a whole number of GiB, including 0.");
  const gib = Number(value.trim());
  const bytes = gib * GIB;
  if (!Number.isSafeInteger(gib) || !Number.isSafeInteger(bytes) || bytes < 0) {
    throw new Error("The storage limit is too large. Choose a smaller amount.");
  }
  return bytes;
}

function invitationParameters(fragment: string, legacySearch: string): URLSearchParams | null {
  if (fragment && !fragment.startsWith("#")) return null;
  const legacy = new URLSearchParams(legacySearch.replace(/^\?/, ""));
  // Không đoán credential khi hai dạng link gửi các selector khác nhau.
  if (fragment.length > 1 && (legacy.has("uid") || legacy.has("token"))) return null;
  return fragment.length > 1 ? new URLSearchParams(fragment.slice(1)) : legacy;
}

/** Link cũ chỉ được đọc khi caller chủ động cho phép; credential luôn giữ trong memory. */
export function organizationInviteFragment(fragment: string, legacySearch = ""): { uid: string; token: string } | null {
  const parameters = invitationParameters(fragment, legacySearch);
  if (!parameters) return null;
  const uid = parameters.get("uid") ?? "";
  const token = parameters.get("token") ?? "";
  if (parameters.getAll("uid").length !== 1 || parameters.getAll("token").length !== 1
      || !uid || uid.length > 128 || !token || token.length > 256 || /\s/.test(uid) || /\s/.test(token)) return null;
  return { uid, token };
}

/** Workspace invite không đưa token vào API query hoặc URL đăng nhập mới. */
export function workspaceInviteToken(fragment: string, legacySearch = ""): string | null {
  const parameters = invitationParameters(fragment, legacySearch);
  const token = parameters?.get("token") ?? "";
  return parameters?.getAll("token").length === 1 && token && token.length <= 256 && !/\s/.test(token) ? token : null;
}
