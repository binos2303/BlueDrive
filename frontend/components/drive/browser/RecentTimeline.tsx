import type { DriveItem } from "./types";
import { recentTimelineDays } from "./recent-timeline";

export default function RecentTimeline({ items }: { items: readonly DriveItem[] }) {
  const days = recentTimelineDays(items, new Date());
  const peak = Math.max(1, ...days.map((day) => day.count));
  const count = days.reduce((total, day) => total + day.count, 0);
  const shortDate = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
  const fullDate = new Intl.DateTimeFormat(undefined, { dateStyle: "full" });

  return (
    <figure className="border-b border-border p-4 sm:p-5" data-no-marquee-selection="true" aria-labelledby="recent-timeline-title">
      <figcaption>
        <h2 id="recent-timeline-title" className="text-sm font-semibold text-foreground">Recent timeline</h2>
        <p className="mt-1 text-xs leading-5 text-muted">Files and folders by latest access or update · last 14 days.</p>
      </figcaption>
      <div tabIndex={0} role="region" aria-label="Daily recent items chart, scroll horizontally on small screens" className="relative mt-4 overflow-x-auto rounded-lg">
        <ol className="grid min-w-[36rem] grid-cols-14 gap-2 pb-2">
          {days.map((day) => (
            <li key={day.date.getTime()} className="min-w-0 text-center text-xs tabular-nums" title={`${fullDate.format(day.date)}: ${day.count} items`}>
              <span className={day.count ? "text-foreground" : "text-muted"}>{day.count}<span className="sr-only"> items</span></span>
              <div aria-hidden="true" className="mt-1 flex h-20 items-end border-b border-border">
                <span className="mx-auto w-full max-w-7 rounded-t-sm bg-brand-contrast" style={{ height: `${day.count / peak * 100}%` }} />
              </div>
              <time dateTime={`${day.date.getFullYear()}-${String(day.date.getMonth() + 1).padStart(2, "0")}-${String(day.date.getDate()).padStart(2, "0")}`} className="mt-2 block whitespace-nowrap text-muted">{shortDate.format(day.date)}</time>
            </li>
          ))}
        </ol>
      </div>
      <p className="mt-2 text-xs leading-5 text-muted">{count === 0 ? "No items in the last 14 days. " : ""}Based on up to 100 recent items; each item is counted once.</p>
    </figure>
  );
}
