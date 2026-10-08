import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  document.cookie = "tfe_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
});

// jsdom lacks these browser APIs used by the app.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
if (typeof HTMLDialogElement !== "undefined" && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
}
window.scrollTo = (() => {}) as typeof window.scrollTo;
// Unovis measures text with canvas; jsdom has none (charts fall back to tables in tests).
HTMLCanvasElement.prototype.getContext = (() => null) as never;
