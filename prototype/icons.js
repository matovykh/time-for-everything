const paths = {
  home: '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
  lessons:
    '<path d="M12 5C9 3 5 3 2 4v15c4-1 7 0 10 2 3-2 6-3 10-2V4c-3-1-7-1-10 1v16"/>',
  walk: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
  chores:
    '<rect x="5" y="4" width="15" height="18" rx="3"/><rect x="9" y="2" width="7" height="4" rx="1"/><path d="m9 13 3 3 5-6"/>',
  world: '<circle cx="12" cy="12" r="9"/><path d="m15 8-2 6-5 2 2-6z"/>',
  rewards: '<path d="m12 2 3 6.5 7 1-5 5 1 7-6-3.5L6 21l1-6.5-5-5 7-1z"/>',
  settings:
    '<path d="m9 3 1-1h4l1 3 3 1 2-1 2 4-2 2v3l2 2-2 4-3-1-2 1-1 3h-4l-1-3-3-1-2 1-2-4 2-2v-3L2 9l2-4 3 1z"/><circle cx="12" cy="12" r="3"/>',
  moon: '<path d="M20 14A9 9 0 0 1 10 3a9 9 0 1 0 10 11Z"/>',
  system:
    '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8m-4-4v4"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 22v-2a8 8 0 0 1 16 0v2"/>',
  exit: '<path d="M9 3H4v18h5m5-14 5 5-5 5m-6-5h13"/>',
  spark:
    '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5zM20 2v4m-2-2h4"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  timer:
    '<circle cx="12" cy="14" r="8"/><path d="M9 2h6m-3 4V2m0 12 3-3m3-6 2 2"/>',
  flag: '<path d="M4 22V3c6-4 10 4 16 0v11c-6 4-10-4-16 0"/>',
  people:
    '<circle cx="9" cy="8" r="3"/><path d="M2 21v-3a7 7 0 0 1 14 0v3m0-17a3 3 0 0 1 0 6m3 5a5 5 0 0 1 3 4v2"/>',
  play: '<path d="m8 4 13 8-13 8Z"/>',
  pause: '<path d="M8 4v16M16 4v16"/>',
};
export function icon(name, size = 22) {
  return `<svg class="ui-icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.spark}</svg>`;
}
