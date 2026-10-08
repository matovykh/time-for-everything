// Types for the prototype's art module (copied verbatim from prototype/world-art.js).
export type WorldArtId = "settlers" | "bricks" | "voxel" | "helpers";
export function worldEmblem(id: string): string;
export function worldScene(
  id: string,
  level: number,
  options?: { motion?: boolean; preview?: boolean },
): string;
export function upgradeArtwork(id: string, index: number): string;
