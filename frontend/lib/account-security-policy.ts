/** Client-side form guidance only; Django remains the password policy authority. */
export function passwordChangeIssue(current: string, next: string, confirmation: string): string | null {
  if (!current || !next || !confirmation) return "Complete all password fields.";
  if (next !== confirmation) return "New passwords do not match.";
  if (next === current) return "Choose a password different from your current password.";
  return null;
}

export function mayHaveNextPage(count: number, page: number, pageSize: number): boolean {
  return page > 0 && pageSize > 0 && Number.isFinite(count) && page * pageSize < count;
}
