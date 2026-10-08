import {
  XYContainer,
  SingleContainer,
  StackedBar,
  Line,
  Scatter,
  Donut,
  Axis,
} from "@unovis/ts";

const colors = ["#3455EB", "#00B8C4", "#FFD23F"];
const names = ["Уроки", "Прогулки", "Другие занятия"];
let instances = [],
  specs = [],
  sequence = 0;
const number = (value) => Math.round(value).toLocaleString("ru-RU");
export function disposeCharts() {
  instances.forEach((chart) => chart.destroy());
  instances = [];
  specs = [];
}
function slot(kind, data, label) {
  const id = `unovis-${++sequence}`;
  specs.push({ id, kind, data });
  return `<div id="${id}" data-unovis="${kind}" class="unovis-host ${kind === "donut" ? "unovis-donut" : ""}" role="img" aria-label="${label}"></div>`;
}
export function stackedChart(data) {
  return (
    slot("stacked", data, "Время по календарным неделям, в минутах") +
    `<div class="legend">${names.map((name, i) => `<span><i style="background:${colors[i]}"></i>${name}</span>`).join("")}</div><small>* Текущая неделя неполная</small><details class="chart-data"><summary>Посмотреть числа</summary><div class="table-wrap"><table><thead><tr><th>Неделя</th>${names.map((n) => `<th>${n}, мин</th>`).join("")}</tr></thead><tbody>${data.map((d) => `<tr><td>${d.label}</td>${d.values.map((v) => `<td>${number(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></details>`
  );
}
export function donutChart(values) {
  const data = values.map((value, i) => ({
    value,
    name: names[i],
    color: colors[i],
  }));
  return `<div class="donut-wrap">${slot("donut", data, "Распределение учтённого времени за 7 дней")}<div class="donut-legend">${data.map((d) => `<div><span style="color:${d.color}">●</span> ${d.name}<b>${number(d.value)} мин</b></div>`).join("")}</div></div>`;
}
export function progressChart(rows) {
  if (!rows.length)
    return '<p class="empty">Пока нет записей за это занятие. Добавь первую — здесь начнётся твоя история.</p>';
  return (
    slot(
      "line",
      rows,
      "Вся история занятия по датам, в минутах. Все записанные даты последовательно соединены линией",
    ) +
    `<details class="chart-data"><summary>Посмотреть числа</summary><table><thead><tr><th>Дата</th><th>Минуты</th></tr></thead><tbody>${rows.map((d) => `<tr><td>${d.date}</td><td>${d.v === undefined ? "Нет записей" : number(d.v)}</td></tr>`).join("")}</tbody></table></details>`
  );
}
export function mountCharts() {
  for (const { id, kind, data } of specs) {
    const node = document.getElementById(id);
    if (!node) continue;
    // Container owns its resize observer and is destroyed before the next route render.
    if (kind === "donut") {
      instances.push(
        new SingleContainer(
          node,
          {
            height: 210,
            component: new Donut({
              value: (d) => d.value,
              color: (d) => d.color,
              arcWidth: 23,
              cornerRadius: 4,
              padAngle: 0.025,
              centralLabel: number(data.reduce((sum, d) => sum + d.value, 0)),
              centralSubLabel: "минут за 7 дней",
              duration: 0,
            }),
          },
          data,
        ),
      );
      continue;
    }
    const dayMs = 86400000;
    const points = data.map((d, i) => ({
      ...d,
      x: kind === "line" ? Date.parse(d.date + "T00:00:00Z") / dayMs : i,
    }));
    const tickLimit = node.clientWidth < 480 ? 3 : 6;
    const ticks =
      kind === "stacked" || points.length <= tickLimit
        ? points.map((d) => d.x)
        : Array.from(
            { length: tickLimit },
            (_, i) =>
              points[Math.round((i * (points.length - 1)) / (tickLimit - 1))].x,
          );
    const firstX = points[0].x,
      lastX = points[points.length - 1].x;
    const xPadding =
      kind === "line" ? Math.max(0.5, (lastX - firstX) * 0.025) : 0.5;
    const maximum = Math.max(
      30,
      ...data.map((d) =>
        kind === "stacked" ? d.values.reduce((s, v) => s + v, 0) : d.v || 0,
      ),
    );
    const components =
      kind === "stacked"
        ? [
            new StackedBar({
              x: (d) => d.x,
              y: [(d) => d.values[0], (d) => d.values[1], (d) => d.values[2]],
              color: colors,
              barWidth: 36,
              roundedCorners: 4,
              duration: 0,
            }),
          ]
        : [
            new Line({
              x: (d) => d.x,
              y: (d) => d.v,
              color: colors[0],
              lineWidth: 3,
              curveType: "linear",
              fallbackValue: undefined,
              interpolateMissingData: false,
              duration: 0,
            }),
            new Scatter({
              x: (d) => d.x,
              y: (d) => d.v,
              color: colors[0],
              size: (d) => (d.v === undefined ? 0 : 7),
              duration: 0,
            }),
          ];
    instances.push(
      new XYContainer(
        node,
        {
          height: 250,
          margin: { top: 14, right: 12, bottom: 8, left: 8 },
          xDomain: [firstX - xPadding, lastX + xPadding],
          yDomain: [
            0,
            Math.ceil(maximum / (kind === "stacked" ? 100 : 10)) *
              (kind === "stacked" ? 100 : 10),
          ],
          components,
          xAxis: new Axis({
            type: "x",
            tickValues: ticks,
            tickFormat: (x) =>
              kind === "stacked"
                ? data[x]?.label || ""
                : new Date(Number(x) * dayMs).toLocaleDateString("ru-RU", {
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
            tickFormat: number,
            tickLine: false,
            domainLine: false,
            tickTextFontSize: "11px",
          }),
        },
        points,
      ),
    );
  }
  specs = [];
}
