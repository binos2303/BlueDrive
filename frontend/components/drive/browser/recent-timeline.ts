type RecentItem = { modifiedAt?: string };

export function recentTimelineDays(items: readonly RecentItem[], today: Date) {
  const days = Array.from({ length: 14 }, (_, index) => {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 13 + index);
    return { date, count: 0 };
  });
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1).getTime();
  for (const item of items) {
    // Display dates are localized; only use the original API timestamp for grouping.
    const timestamp = item.modifiedAt ? Date.parse(item.modifiedAt) : NaN;
    if (!Number.isFinite(timestamp) || timestamp < days[0].date.getTime() || timestamp >= end) continue;
    const index = days.findIndex((day, index) => timestamp >= day.date.getTime()
      && timestamp < (days[index + 1]?.date.getTime() ?? end));
    if (index !== -1) days[index].count += 1;
  }
  return days;
}
