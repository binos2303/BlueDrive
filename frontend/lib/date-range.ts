export function inLocalDateRange(value: string, from: string, to: string): boolean {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return false;
  const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  return (!from || day >= from) && (!to || day <= to);
}
