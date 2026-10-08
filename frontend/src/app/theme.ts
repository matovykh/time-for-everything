import { useCallback, useEffect, useSyncExternalStore } from "react";

export type ThemeChoice = "light" | "dark" | "system";
const KEY = "vse-uspeyu-theme";
const media = () =>
  typeof matchMedia === "function"
    ? matchMedia("(prefers-color-scheme: dark)")
    : null;

// The theme choice is a non-sensitive UI preference, so it lives in
// localStorage; it also works on the login screen before a session exists.
function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" || v === "system" ? v : "system";
  } catch {
    return "system";
  }
}

const listeners = new Set<() => void>();
let current: ThemeChoice = readChoice();

export function resolvedTheme(choice: ThemeChoice): "light" | "dark" {
  if (choice !== "system") return choice;
  return media()?.matches ? "dark" : "light";
}

export function applyTheme(choice: ThemeChoice = current) {
  const resolved = resolvedTheme(choice);
  document.body.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
  document.body.classList.toggle("theme-dark", resolved === "dark");
}

export function setThemeChoice(choice: ThemeChoice) {
  current = choice;
  try {
    localStorage.setItem(KEY, choice);
  } catch {
    /* storage unavailable: keep in memory */
  }
  applyTheme(choice);
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Effective light/dark value, re-rendering on choice or OS changes. */
export function useResolvedTheme(): "light" | "dark" {
  const choice = useSyncExternalStore(subscribe, () => current);
  const osDark = useSyncExternalStore(
    (cb) => {
      const mq = media();
      mq?.addEventListener("change", cb);
      return () => mq?.removeEventListener("change", cb);
    },
    () => Boolean(media()?.matches),
  );
  return choice === "system" ? (osDark ? "dark" : "light") : choice;
}

export function useTheme() {
  const choice = useSyncExternalStore(subscribe, () => current);
  useEffect(() => {
    applyTheme(choice);
    const mq = media();
    if (!mq) return;
    // System theme follows OS changes without reload.
    const onChange = () => applyTheme(current);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [choice]);
  const set = useCallback((c: ThemeChoice) => setThemeChoice(c), []);
  return [choice, set] as const;
}
