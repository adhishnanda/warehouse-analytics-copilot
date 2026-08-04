// Ported 1:1 from .streamlit/config.toml (the project's original chart
// theme) - a validated, colorblind-safe categorical palette (fixed hue
// order, checked for adjacent-pair CVD separation and surface contrast),
// not an arbitrary default color cycle. Single source of truth: if this
// ever needs to change, change it there too, or retire that file's
// comment pointing here.
export const CATEGORICAL_PALETTE = [
  "#2a78d6", // blue
  "#eb6834", // orange
  "#1baf7a", // aqua
  "#eda100", // yellow
  "#e87ba4", // magenta
  "#008300", // green
  "#4a3aa7", // violet
  "#e34948", // red
] as const;

// Reserved for state, not "just another series" - mode-invariant hexes
// (same value renders with sufficient contrast on both light and dark
// chart surfaces), used only for charts that represent success/failure.
export const STATUS_GOOD = "#0ca30c";
export const STATUS_CRITICAL = "#d03b3b";
