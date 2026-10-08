// Chart palettes, validated with the dataviz validator (light surface #fcfcfb,
// dark surface #1a2540). Light-mode slots below 3:1 contrast are relieved by
// the always-visible legend and the "Посмотреть числа" table.
//
// Category order follows the approved prototype: Уроки (primary blue),
// Прогулки (rest teal), Другие занятия (gold). The prototype's #FFD23F fails the
// lightness band for marks, so charts use the deeper gold #eda100.

export type Mode = "light" | "dark";

export const CATEGORY_KEYS = ["lessons", "walk", "other"] as const;
export const CATEGORY_LABELS: Record<string, string> = {
  lessons: "Уроки",
  walk: "Прогулки",
  other: "Другие занятия",
};

const CATEGORY: Record<Mode, Record<string, string>> = {
  light: { lessons: "#3455EB", walk: "#00B8C4", other: "#eda100" },
  dark: { lessons: "#5a78ff", walk: "#00a3ae", other: "#c98500" },
};

// 8 fixed slots, assigned by the activity's stable catalogue position —
// colour follows the entity, never its rank in a filtered view.
const SLOTS: Record<Mode, string[]> = {
  light: ["#3455EB", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
  dark: ["#5a78ff", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
};

export const MAX_ACTIVITY_SLOTS = SLOTS.light.length;
export const OTHER_KEY = "__other__";

export function categoryColor(key: string, mode: Mode): string {
  return CATEGORY[mode][key] ?? SLOTS[mode][7];
}

export function slotColor(index: number, mode: Mode): string {
  return SLOTS[mode][Math.min(index, SLOTS[mode].length - 1)];
}

export const lineColor = (mode: Mode) => CATEGORY[mode].lessons;
