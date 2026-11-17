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

/** Fragment chỉ được giữ trong memory; không đọc token từ query hoặc browser storage. */
export function organizationInviteFragment(fragment: string): { uid: string; token: string } | null {
  if (!fragment.startsWith("#")) return null;
  const parameters = new URLSearchParams(fragment.replace(/^#/, ""));
  const uid = parameters.get("uid") ?? "";
  const token = parameters.get("token") ?? "";
  if (parameters.getAll("uid").length !== 1 || parameters.getAll("token").length !== 1
      || !uid || uid.length > 128 || !token || token.length > 256 || /\s/.test(uid) || /\s/.test(token)) return null;
  return { uid, token };
}
