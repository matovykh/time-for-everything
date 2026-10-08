// Calendar helpers. Report dates are local ISO dates (YYYY-MM-DD) in the
// profile timezone; durations are integer seconds (SPECIFICATION §4.1).

const pad = (n: number) => String(n).padStart(2, "0");

/** Local calendar date in an IANA timezone (falls back to the browser zone). */
export function todayIn(timeZone?: string | null, now: Date = new Date()): string {
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: timeZone || undefined,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(now);
    const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
    return `${get("year")}-${get("month")}-${get("day")}`;
  } catch {
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  }
}

export const isIsoDate = (s: string) =>
  /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(s + "T00:00:00Z"));

/** Day number since epoch for an ISO date — calendar-correct, no DST effects. */
export const dayNumber = (iso: string) =>
  Math.round(Date.parse(iso + "T00:00:00Z") / 86_400_000);

export const fromDayNumber = (n: number) =>
  new Date(n * 86_400_000).toISOString().slice(0, 10);

export function addDays(iso: string, days: number): string {
  return fromDayNumber(dayNumber(iso) + days);
}

/** Monday of the ISO week that contains the date. */
export function weekStart(iso: string): string {
  const d = new Date(iso + "T00:00:00Z");
  const shift = (d.getUTCDay() + 6) % 7;
  return addDays(iso, -shift);
}

/** 25.10.2026 */
export const ruDate = (iso: string) => iso.split("-").reverse().join(".");

/** 5 окт. */
export function ruShortDate(iso: string): string {
  return new Date(iso + "T00:00:00Z").toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

export function ruLongToday(timeZone?: string | null): string {
  try {
    return new Date().toLocaleDateString("ru-RU", {
      day: "numeric",
      month: "long",
      weekday: "short",
      timeZone: timeZone || undefined,
    });
  } catch {
    return new Date().toLocaleDateString("ru-RU", {
      day: "numeric",
      month: "long",
      weekday: "short",
    });
  }
}

export function ruDateTime(isoTimestamp: string): string {
  const d = new Date(isoTimestamp);
  if (Number.isNaN(d.getTime())) return isoTimestamp;
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** HH:MM:SS from milliseconds (display only). */
export function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60]
    .map(pad)
    .join(":");
}

export const minutesOf = (seconds: number) => seconds / 60;

export const fmt = (n: number) => Math.round(n).toLocaleString("ru-RU");

/** "1 ч 05 мин" / "25 мин" / "40 с" for history rows. */
export function duration(seconds: number): string {
  if (seconds < 60) return `${seconds} с`;
  const totalMin = Math.round(seconds / 60);
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return h ? `${h} ч ${pad(m)} мин` : `${m} мин`;
}

/** Russian plural: plural(5, ["запись","записи","записей"]) */
export function plural(n: number, forms: [string, string, string]): string {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b > 1 && b < 5) return forms[1];
  if (b === 1) return forms[0];
  return forms[2];
}
