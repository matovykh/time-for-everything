import { useEffect, useSyncExternalStore } from "react";

// Hash routing keeps the SPA independent from server-side fallback rules
// (FastAPI only has to serve index.html at "/").
export type Route =
  | { page: "home" }
  | { page: "lessons" }
  | { page: "walk" }
  | { page: "activity"; id: string }
  | { page: "chores" }
  | { page: "world" }
  | { page: "rewards" }
  | { page: "settings" }
  | { page: "profile" };

const simple = new Set([
  "home",
  "lessons",
  "walk",
  "chores",
  "world",
  "rewards",
  "settings",
  "profile",
]);

export function parseHash(hash: string): Route {
  const [p, id] = hash.replace(/^#\/?/, "").split("/");
  if (p === "activity" && id) return { page: "activity", id: decodeURIComponent(id) };
  if (simple.has(p)) return { page: p } as Route;
  return { page: "home" };
}

export function hrefFor(route: Route): string {
  return route.page === "activity"
    ? `#activity/${encodeURIComponent(route.id)}`
    : `#${route.page}`;
}

export function navigate(route: Route) {
  const next = hrefFor(route);
  if (location.hash === next) return;
  location.hash = next;
}

function subscribe(cb: () => void) {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, () => location.hash);
  useEffect(() => {
    window.scrollTo?.(0, 0);
  }, [hash]);
  return parseHash(hash);
}
