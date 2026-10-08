import { useEffect, useRef } from "react";
import {
  Axis,
  Donut,
  Line,
  Scatter,
  SingleContainer,
  StackedBar,
  Tooltip,
  XYContainer,
} from "@unovis/ts";
import { fmt, ruDate, dayNumber } from "../dates";
import { lineColor, type Mode } from "./palette";

const DAY_MS = 86_400_000;

const esc = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

/** Creates a Unovis container on mount/data change and destroys it on cleanup. */
function useUnovis(build: (node: HTMLDivElement) => { destroy: () => void } | null, deps: unknown[]) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    let chart: { destroy: () => void } | null = null;
    try {
      chart = build(node);
    } catch {
      // jsdom / very old browsers: the numeric table stays as the fallback.
      chart = null;
    }
    return () => {
      chart?.destroy();
      node.innerHTML = "";
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return ref;
}

export interface ChartSeries {
  key: string;
  label: string;
  color: string;
}

export interface WeekBar {
  label: string;
  complete: boolean;
  /** Minutes per series key. */
  values: Record<string, number>;
}

export function WeekStackChart({ weeks, series }: { weeks: WeekBar[]; series: ChartSeries[] }) {
  const sig = JSON.stringify([weeks, series]);
  const ref = useUnovis((node) => {
    if (!weeks.length || !series.length) return null;
    const points = weeks.map((w, i) => ({ ...w, x: i }));
    const max = Math.max(30, ...weeks.map((w) => series.reduce((s, k) => s + (w.values[k.key] ?? 0), 0)));
    const narrow = node.clientWidth < 480;
    const step = weeks.length > 6 && narrow ? Math.ceil(weeks.length / 4) : weeks.length > 8 ? 2 : 1;
    return new XYContainer<(typeof points)[number]>(
      node,
      {
        height: 250,
        margin: { top: 14, right: 12, bottom: 8, left: 8 },
        xDomain: [-0.5, weeks.length - 0.5],
        yDomain: [0, Math.ceil(max / 100) * 100],
        components: [
          new StackedBar<(typeof points)[number]>({
            x: (d) => d.x,
            y: series.map((s) => (d: (typeof points)[number]) => d.values[s.key] ?? 0),
            color: series.map((s) => s.color),
            barMaxWidth: 36,
            roundedCorners: 4,
            duration: 0,
          }),
        ],
        tooltip: new Tooltip({
          triggers: {
            [StackedBar.selectors.bar]: (d: (typeof points)[number]) =>
              `<b>Неделя с ${esc(d.label)}</b><br>` +
              series
                .map((s) => `<span style="color:${s.color}">●</span> ${esc(s.label)}: ${fmt(d.values[s.key] ?? 0)} мин`)
                .join("<br>"),
          },
        }),
        xAxis: new Axis({
          type: "x",
          tickValues: points.filter((_, i) => i % step === 0 || i === points.length - 1).map((p) => p.x),
          tickFormat: (x) => points[Number(x)]?.label ?? "",
          gridLine: false,
          tickLine: false,
          domainLine: false,
          tickTextFontSize: "11px",
        }),
        yAxis: new Axis({
          type: "y",
          label: "Минуты",
          numTicks: 4,
          tickFormat: (v) => fmt(Number(v)),
          tickLine: false,
          domainLine: false,
          tickTextFontSize: "11px",
        }),
      },
      points,
    );
  }, [sig]);

  return (
    <>
      <div ref={ref} className="unovis-host" role="img" aria-label="Время по календарным неделям (понедельник–воскресенье), в минутах" />
      <div className="legend">
        {series.map((s) => (
          <span key={s.key}>
            <i style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
      {weeks.some((w) => !w.complete) && <small>* Текущая неделя ещё не закончилась — её не стоит сравнивать с полными.</small>}
      <details className="chart-data">
        <summary>Посмотреть числа</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Неделя</th>
                {series.map((s) => (
                  <th key={s.key}>{s.label}, мин</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {weeks.map((w) => (
                <tr key={w.label}>
                  <td>{w.label}</td>
                  {series.map((s) => (
                    <td key={s.key}>{fmt(w.values[s.key] ?? 0)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

export interface DonutSlice {
  key: string;
  label: string;
  minutes: number;
  color: string;
}

export function TimeDonut({ slices, subLabel }: { slices: DonutSlice[]; subLabel: string }) {
  const total = slices.reduce((s, d) => s + d.minutes, 0);
  const sig = JSON.stringify([slices, subLabel]);
  const ref = useUnovis((node) => {
    const data = slices.filter((s) => s.minutes > 0);
    if (!data.length) return null;
    return new SingleContainer<DonutSlice[]>(
      node,
      {
        height: 210,
        tooltip: new Tooltip({
          triggers: {
            [Donut.selectors.segment]: (d: { data: DonutSlice }) =>
              `${esc(d.data.label)}: ${fmt(d.data.minutes)} мин · ${total ? Math.round((d.data.minutes / total) * 100) : 0}%`,
          },
        }),
        component: new Donut<DonutSlice>({
          value: (d) => d.minutes,
          color: (d) => d.color,
          arcWidth: 23,
          cornerRadius: 4,
          padAngle: 0.025,
          centralLabel: fmt(total),
          centralSubLabel: subLabel,
          duration: 0,
        }),
      },
      data,
    );
  }, [sig]);

  if (total <= 0)
    return <p className="empty">За этот период ещё нет записанного времени. Включи таймер или добавь запись вручную.</p>;
  return (
    <div className="donut-wrap">
      <div ref={ref} className="unovis-host unovis-donut" role="img" aria-label={`Распределение учтённого времени: всего ${fmt(total)} минут`} />
      <div className="donut-legend">
        {slices.map((d) => (
          <div key={d.key}>
            <span style={{ color: d.color }} aria-hidden="true">
              ●
            </span>{" "}
            {d.label}
            <b>
              {fmt(d.minutes)} мин · {total ? Math.round((d.minutes / total) * 100) : 0}%
            </b>
          </div>
        ))}
      </div>
    </div>
  );
}

export interface LinePoint {
  date: string;
  minutes: number;
  entries: number;
}

/**
 * All-time history: one point per recorded date (already aggregated by the
 * server), sorted ascending and joined in sequence. Dates without entries are
 * not zero-filled; the x scale is calendar days, so gaps keep real spacing.
 * Only axis labels are thinned, never the points.
 */
export function ProgressLine({ points, mode }: { points: LinePoint[]; mode: Mode }) {
  const sorted = [...points].sort((a, b) => a.date.localeCompare(b.date));
  const sig = JSON.stringify([sorted, mode]);
  const ref = useUnovis((node) => {
    if (!sorted.length) return null;
    const data = sorted.map((p) => ({ ...p, x: dayNumber(p.date) }));
    const color = lineColor(mode);
    const tickLimit = node.clientWidth < 480 ? 3 : 6;
    const first = data[0].x;
    const last = data[data.length - 1].x;
    // Only axis labels are thinned: evenly spaced calendar days so labels never
    // collide when recorded dates cluster. Every data point is still drawn.
    const ticks =
      last === first
          ? [first]
          : (() => {
              const n = Math.min(tickLimit, last - first + 1);
              return Array.from({ length: n }, (_, i) => Math.round(first + (i * (last - first)) / Math.max(1, n - 1)));
            })();
    const pad = Math.max(0.5, (last - first) * 0.025);
    const max = Math.max(30, ...data.map((d) => d.minutes));
    return new XYContainer<(typeof data)[number]>(
      node,
      {
        height: 250,
        margin: { top: 14, right: 12, bottom: 8, left: 8 },
        xDomain: [first - pad, last + pad],
        yDomain: [0, Math.ceil(max / 10) * 10],
        components: [
          new Line<(typeof data)[number]>({
            x: (d) => d.x,
            y: (d) => d.minutes,
            color,
            lineWidth: 2,
            curveType: "linear" as never,
            interpolateMissingData: false,
            duration: 0,
          }),
          new Scatter<(typeof data)[number]>({
            x: (d) => d.x,
            y: (d) => d.minutes,
            color,
            size: 8,
            strokeColor: "var(--surface)",
            strokeWidth: 2,
            duration: 0,
          }),
        ],
        tooltip: new Tooltip({
          triggers: {
            [Scatter.selectors.point]: (d: (typeof data)[number]) =>
              `<b>${ruDate(d.date)}</b><br>${fmt(d.minutes)} мин · записей: ${d.entries}`,
          },
        }),
        xAxis: new Axis({
          type: "x",
          tickValues: ticks,
          tickFormat: (x) =>
            new Date(Number(x) * DAY_MS).toLocaleDateString("ru-RU", {
              day: "2-digit",
              month: "2-digit",
              year: "2-digit",
              timeZone: "UTC",
            }),
          gridLine: false,
          tickLine: false,
          domainLine: false,
          tickTextFontSize: "11px",
          minMaxTicksOnlyWhenWidthIsLess: 0,
        }),
        yAxis: new Axis({
          type: "y",
          label: "Минуты",
          numTicks: 4,
          tickFormat: (v) => fmt(Number(v)),
          tickLine: false,
          domainLine: false,
          tickTextFontSize: "11px",
        }),
      },
      data,
    );
  }, [sig]);

  if (!sorted.length)
    return <p className="empty">Пока нет записей за это занятие. Добавь первую — здесь начнётся твоя история.</p>;
  return (
    <>
      <div
        ref={ref}
        className="unovis-host"
        role="img"
        aria-label={`Вся история занятия: ${sorted.length} дат с записями, по минутам за день. Все записанные даты последовательно соединены линией`}
      />
      <details className="chart-data">
        <summary>Посмотреть числа</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Дата</th>
                <th>Минуты</th>
                <th>Записей</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((d) => (
                <tr key={d.date}>
                  <td>{ruDate(d.date)}</td>
                  <td>{fmt(d.minutes)}</td>
                  <td>{d.entries}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
