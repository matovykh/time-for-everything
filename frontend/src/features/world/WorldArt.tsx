import { memo } from "react";
import { upgradeArtwork, worldEmblem, worldScene } from "../../world-art/world-art.js";

// world-art.js returns trusted, self-authored SVG strings (no user input is
// interpolated: only the theme code and level, which the module whitelists).

/** Animated (motion) or static island scene. Unmounting removes the DOM, which stops the animation. */
export const WorldScene = memo(function WorldScene({
  code,
  level,
  motion,
}: {
  code: string;
  level: number;
  motion: boolean;
}) {
  return (
    <div
      className="scene-host"
      dangerouslySetInnerHTML={{ __html: worldScene(code, level, { motion }) }}
    />
  );
});

export const WorldEmblem = memo(function WorldEmblem({ code }: { code: string }) {
  return <span className="world-emblem" dangerouslySetInnerHTML={{ __html: worldEmblem(code) }} />;
});

export const CatalogEmblem = memo(function CatalogEmblem({ code }: { code: string }) {
  return <div className="catalog-emblem" dangerouslySetInnerHTML={{ __html: worldEmblem(code) }} />;
});

export const UpgradeArt = memo(function UpgradeArt({ code, index }: { code: string; index: number }) {
  return <span className="upgrade-art-host" dangerouslySetInnerHTML={{ __html: upgradeArtwork(code, index) }} />;
});

/** Theme codes the bundled art supports; others fall back to settlers art. */
export const ART_CODES = ["settlers", "bricks", "voxel", "helpers"];
