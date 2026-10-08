import { describe, expect, it } from "vitest";
import { addDays, clock, dayNumber, duration, plural, todayIn, weekStart } from "../shared/dates";
import { parseDuration } from "../features/time-entries/EntryForm";
import { toCharts } from "../features/dashboard/analytics";
import { weekdaysFor } from "../features/settings/SettingsPage";
import { parseHash } from "../app/router";
import type { Analytics } from "../shared/api/types";
import { activity } from "./mockApi";

describe("dates", () => {
  it("computes Monday week starts and calendar days without DST drift", () => {
    expect(weekStart("2026-10-06")).toBe("2026-10-05"); // Tuesday → Monday
    expect(weekStart("2026-10-11")).toBe("2026-10-05"); // Sunday → Monday
    expect(addDays("2026-03-28", 2)).toBe("2026-03-30");
    expect(dayNumber("2026-10-06") - dayNumber("2026-06-01")).toBe(127);
  });
  it("formats timers and durations", () => {
    expect(clock(3_725_000)).toBe("01:02:05");
    expect(clock(-5)).toBe("00:00:00");
    expect(duration(1500)).toBe("25 мин");
    expect(duration(3900)).toBe("1 ч 05 мин");
    expect(duration(40)).toBe("40 с");
    expect(plural(12, ["неделя", "недели", "недель"])).toBe("недель");
    expect(plural(4, ["неделя", "недели", "недель"])).toBe("недели");
  });
  it("uses the profile timezone for today", () => {
    const late = new Date("2026-10-05T22:30:00Z"); // 01:30 next day in Moscow
    expect(todayIn("Europe/Moscow", late)).toBe("2026-10-06");
    expect(todayIn("UTC", late)).toBe("2026-10-05");
  });
});

describe("manual entry duration", () => {
  it("accepts 1 minute to 24 hours only", () => {
    expect(parseDuration("", "25")).toBe(1500);
    expect(parseDuration("1", "30")).toBe(5400);
    expect(parseDuration("", "90")).toBe(5400);
    expect(parseDuration("24", "")).toBe(86400);
    expect(parseDuration("24", "1")).toBeNull();
    expect(parseDuration("", "0")).toBeNull();
    expect(parseDuration("", "1.5")).toBeNull();
    expect(parseDuration("-1", "70")).toBeNull();
  });
});

describe("schedules", () => {
  it("maps schedule kinds to ISO weekdays", () => {
    expect(weekdaysFor("weekdays", 5, [])).toEqual([1, 2, 3, 4, 5]);
    expect(weekdaysFor("weekly", 5, [])).toEqual([5]);
    expect(weekdaysFor("custom", 1, [5, 1, 3, 1])).toEqual([1, 3, 5]);
    expect(weekdaysFor("none", 1, [])).toBeNull();
  });
});

describe("router", () => {
  it("parses hashes", () => {
    expect(parseHash("#activity/abc%20d")).toEqual({ page: "activity", id: "abc d" });
    expect(parseHash("#walk")).toEqual({ page: "walk" });
    expect(parseHash("#nope")).toEqual({ page: "home" });
  });
});

const base: Omit<Analytics, "series" | "buckets" | "totals" | "group_by"> = {
  timezone: "Europe/Moscow",
  bucket: "week",
  from: "2026-09-28",
  to: "2026-10-11",
  total_seconds: 0,
};

describe("analytics → charts", () => {
  it("keeps category order/colours and marks the incomplete week", () => {
    const r = toCharts(
      {
        ...base,
        group_by: "category",
        series: [
          { key: "lessons", label: "Уроки" },
          { key: "walk", label: "Прогулки" },
          { key: "other", label: "Другие занятия" },
        ],
        buckets: [
          { start: "2026-09-28", end: "2026-10-04", complete: true, totals: { lessons: 600, walk: 1200, other: 0 }, total_seconds: 1800 },
          { start: "2026-10-05", end: "2026-10-11", complete: false, totals: { lessons: 60, walk: 0, other: 120 }, total_seconds: 180 },
        ],
        totals: { lessons: 660, walk: 1200, other: 120 },
      },
      "light",
    );
    expect(r.series.map((s) => s.color)).toEqual(["#3455EB", "#00B8C4", "#eda100"]);
    expect(r.weeks[0].values).toEqual({ lessons: 10, walk: 20, other: 0 });
    expect(r.weeks[1].label.endsWith("*")).toBe(true);
    expect(r.slices.map((s) => s.minutes)).toEqual([11, 20, 2]);
  });

  it("colours activities by catalogue position and folds overflow into one series", () => {
    const catalogue = Array.from({ length: 10 }, (_, i) => activity({ id: `a${i}`, name: `A${i}` })) as never[];
    const series = [9, 0, 3, 8].map((i) => ({ key: `a${i}`, label: `A${i}` }));
    const r = toCharts(
      {
        ...base,
        group_by: "activity",
        series,
        buckets: [{ start: "2026-10-05", end: "2026-10-11", complete: false, totals: { a9: 60, a0: 120, a3: 180, a8: 240 }, total_seconds: 600 }],
        totals: { a9: 60, a0: 120, a3: 180, a8: 240 },
      },
      "light",
      catalogue,
    );
    expect(r.series.map((s) => s.key)).toEqual(["a0", "a3", "__other__"]);
    expect(r.series[0].color).toBe("#3455EB");
    expect(r.series[1].color).toBe("#eda100"); // slot 4 regardless of the filtered rank
    expect(r.weeks[0].values.__other__).toBe(5); // a9 + a8 = 300 s
  });
});
