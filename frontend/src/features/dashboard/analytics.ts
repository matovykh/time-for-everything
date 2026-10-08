import type { Activity, Analytics } from "../../shared/api/types";
import { ruShortDate } from "../../shared/dates";
import type { ChartSeries, DonutSlice, WeekBar } from "../../shared/charts/Charts";
import {
  CATEGORY_LABELS,
  MAX_ACTIVITY_SLOTS,
  OTHER_KEY,
  categoryColor,
  slotColor,
  type Mode,
} from "../../shared/charts/palette";

/**
 * Turns GET /analytics/time into chart input. In activity mode colours are
 * keyed by each activity's position in the full (incl. archived) catalogue so
 * that a colour always means the same activity; activities beyond the 7th
 * colour slot fold into «Ещё занятия».
 */
export function toCharts(
  data: Analytics,
  mode: Mode,
  catalogue: Activity[] = [],
): { weeks: WeekBar[]; series: ChartSeries[]; slices: DonutSlice[] } {
  const order = new Map(
    catalogue.filter((a) => a.kind === "timed").map((a, i) => [a.id, i] as const),
  );
  const fold = new Map<string, string>(); // series key → displayed key
  const series: ChartSeries[] = [];
  let otherAdded = false;

  for (const s of data.series) {
    if (data.group_by === "category") {
      series.push({ key: s.key, label: CATEGORY_LABELS[s.key] ?? s.label, color: categoryColor(s.key, mode) });
      fold.set(s.key, s.key);
      continue;
    }
    const idx = order.get(s.key) ?? Number.POSITIVE_INFINITY;
    if (idx < MAX_ACTIVITY_SLOTS - 1) {
      series.push({ key: s.key, label: s.label, color: slotColor(idx, mode) });
      fold.set(s.key, s.key);
    } else {
      fold.set(s.key, OTHER_KEY);
      if (!otherAdded) otherAdded = true;
    }
  }
  if (data.group_by === "activity") {
    series.sort((a, b) => (order.get(a.key) ?? 0) - (order.get(b.key) ?? 0));
    if (otherAdded) series.push({ key: OTHER_KEY, label: "Ещё занятия", color: slotColor(MAX_ACTIVITY_SLOTS - 1, mode) });
  }

  const weeks: WeekBar[] = data.buckets.map((b) => {
    const values: Record<string, number> = {};
    for (const [k, sec] of Object.entries(b.totals)) {
      const key = fold.get(k) ?? OTHER_KEY;
      values[key] = (values[key] ?? 0) + sec / 60;
    }
    return { label: ruShortDate(b.start) + (b.complete ? "" : " *"), complete: b.complete, values };
  });

  const totals: Record<string, number> = {};
  for (const [k, sec] of Object.entries(data.totals)) {
    const key = fold.get(k) ?? OTHER_KEY;
    totals[key] = (totals[key] ?? 0) + sec / 60;
  }
  const slices: DonutSlice[] = series.map((s) => ({
    key: s.key,
    label: s.label,
    minutes: totals[s.key] ?? 0,
    color: s.color,
  }));

  return { weeks, series, slices };
}
