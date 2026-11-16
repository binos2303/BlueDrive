/** UI permission guard only. The Django API remains authoritative. */
export type ShareableItem = { owner: string; canManage?: boolean };

export function canOpenShareManagement(items: readonly ShareableItem[]): boolean {
  return items.length > 0 && items.every((item) => item.owner === "Me" && item.canManage !== false);
}
