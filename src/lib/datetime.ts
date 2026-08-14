/**
 * Every date Locus shows is rendered in IST.
 *
 * Not the viewer's local zone. The team this is built for works in one
 * timezone, and the things being timestamped — a review round, a QA reply, a
 * merge — are shared events people talk to each other about. Rendering in the
 * browser's zone means someone on a laptop still set to UTC, or travelling,
 * reads a different wall clock for the same event than the person sitting next
 * to them, and neither has any way to notice. "The build broke at 3" has to
 * mean one moment.
 *
 * `toLocaleString(undefined, …)` is what produced that, and it is the thing
 * these helpers exist to replace. Passing an explicit `timeZone` makes the
 * output independent of where the browser thinks it is.
 *
 * This assumes the backend sends an offset (`…+05:30` or `…Z`). It does —
 * `app/services/datetimes.py` and the API's tz-aware columns guarantee it. A
 * timestamp with no offset is ambiguous and JavaScript resolves it against the
 * browser's zone, which is exactly the bug being fixed, so `parseInstant`
 * treats a bare timestamp as UTC rather than letting it drift.
 */

/** The zone every timestamp is displayed in. */
export const DISPLAY_TIMEZONE = "Asia/Kolkata";

/** Short label for the zone, so a rendered time says which clock it is on. */
export const DISPLAY_TIMEZONE_LABEL = "IST";

/**
 * Turn an API timestamp into a Date.
 *
 * A string carrying no timezone is read as UTC. Postgres returns tz-aware
 * values and SQLite does not, so a naive string means "the backend stored UTC
 * without labelling it" — assuming the browser's zone instead would shift the
 * time by the viewer's offset and produce exactly the inconsistency this
 * module exists to prevent.
 */
export const parseInstant = (iso?: string | null): Date | null => {
  if (!iso) return null;

  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso.trim());
  const value = new Date(hasZone ? iso : `${iso}Z`);

  return Number.isNaN(value.getTime()) ? null : value;
};

const format = (
  iso: string | null | undefined,
  options: Intl.DateTimeFormatOptions,
  fallback: string
): string => {
  const value = parseInstant(iso);
  if (!value) return fallback;

  // "en-IN" rather than the browser's locale: the zone is fixed, so the date
  // order should be too. A shared timestamp that reads 03/04 to one person
  // and 04/03 to another is the same failure in a different field.
  return new Intl.DateTimeFormat("en-IN", {
    ...options,
    timeZone: DISPLAY_TIMEZONE,
  }).format(value);
};

/** "14 Aug, 08:23 pm" — the default for a timestamp in a list. */
export const formatDateTime = (iso?: string | null, fallback = ""): string =>
  format(
    iso,
    { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" },
    fallback
  );

/** "Thu, 14 Aug, 08:23 pm" — when the weekday matters, as in a schedule. */
export const formatWithWeekday = (iso?: string | null, fallback = ""): string =>
  format(
    iso,
    {
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    },
    fallback
  );

/** "14 Aug 2026, 08:23 pm" — full form, for a detail view. */
export const formatFull = (iso?: string | null, fallback = ""): string =>
  format(
    iso,
    {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    },
    fallback
  );

/** "14 Aug 2026" — date only. */
export const formatDate = (iso?: string | null, fallback = ""): string =>
  format(iso, { day: "numeric", month: "short", year: "numeric" }, fallback);

/**
 * "3 minutes ago" — elapsed time, which is zone-independent.
 *
 * Included here so callers reach for one module rather than hand-rolling the
 * arithmetic next to a correctly-zoned absolute time.
 *
 * "never" is a real answer, not a missing value: a service with a failure
 * streak and no successful call has genuinely never worked.
 */
export const timeAgo = (iso?: string | null, never = "never"): string => {
  const value = parseInstant(iso);
  if (!value) return never;

  const seconds = (Date.now() - value.getTime()) / 1000;
  if (seconds < 60) return "just now";

  const scales: [number, string][] = [
    [86400, "day"],
    [3600, "hour"],
    [60, "minute"],
  ];
  for (const [size, label] of scales) {
    if (seconds >= size) {
      const n = Math.round(seconds / size);
      return `${n} ${label}${n === 1 ? "" : "s"} ago`;
    }
  }
  return "just now";
};
