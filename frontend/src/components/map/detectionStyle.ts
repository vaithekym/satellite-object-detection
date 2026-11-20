import type { ExpressionSpecification } from "maplibre-gl";
import type { DetectionCollection, DetectionFeature } from "../../services/detections";

/** Display name (Norwegian) and colour per DOTA class. Unknown classes fall back to grey. */
export const CLASS_STYLES: Record<string, { label: string; color: string }> = {
  plane: { label: "Fly", color: "#ef4444" },
  helicopter: { label: "Helikopter", color: "#f97316" },
  ship: { label: "Skip", color: "#3b82f6" },
  harbor: { label: "Havn", color: "#0ea5e9" },
  "storage tank": { label: "Lagertank", color: "#d946ef" },
  "large vehicle": { label: "Stort kjøretøy", color: "#f59e0b" },
  "small vehicle": { label: "Liten bil", color: "#eab308" },
  bridge: { label: "Bro", color: "#8b5cf6" },
  roundabout: { label: "Rundkjøring", color: "#14b8a6" },
  "baseball diamond": { label: "Baseballbane", color: "#22c55e" },
  "tennis court": { label: "Tennisbane", color: "#22c55e" },
  "basketball court": { label: "Basketballbane", color: "#22c55e" },
  "soccer ball field": { label: "Fotballbane", color: "#22c55e" },
  "ground track field": { label: "Friidrettsbane", color: "#22c55e" },
  "swimming pool": { label: "Svømmebasseng", color: "#06b6d4" },
};
const FALLBACK_COLOR = "#94a3b8";

export function classLabel(className: string): string {
  return CLASS_STYLES[className]?.label ?? className;
}

export function classColor(className: string): string {
  return CLASS_STYLES[className]?.color ?? FALLBACK_COLOR;
}

/** MapLibre expression: colour by the feature's class_name. */
export const classColorExpression = [
  "match",
  ["get", "class_name"],
  ...Object.entries(CLASS_STYLES).flatMap(([name, style]) => [name, style.color]),
  FALLBACK_COLOR,
] as unknown as ExpressionSpecification;

export interface DetectionFilter {
  minConfidence: number;
  hiddenClasses: Record<string, true>;
}

/** Merge per-image collections, apply filters, and add a `label` ("Fly 93 %") for the map. */
export function visibleDetections(
  collections: DetectionCollection[],
  filter: DetectionFilter,
): DetectionCollection {
  const features: DetectionFeature[] = [];
  for (const collection of collections) {
    for (const feature of collection.features) {
      const { class_name, confidence } = feature.properties;
      if (confidence < filter.minConfidence || filter.hiddenClasses[class_name]) continue;
      features.push({
        ...feature,
        properties: {
          ...feature.properties,
          detection_id: String(feature.id ?? ""),
          label: `${classLabel(class_name)} ${Math.round(confidence * 100)} %`,
        } as DetectionFeature["properties"],
      });
    }
  }
  return { type: "FeatureCollection", features };
}

/** Number of detections per class at or above the confidence threshold (for the legend). */
export function countByClass(
  collections: DetectionCollection[],
  minConfidence: number,
): [string, number][] {
  const counts = new Map<string, number>();
  for (const collection of collections) {
    for (const { properties } of collection.features) {
      if (properties.confidence >= minConfidence) {
        counts.set(properties.class_name, (counts.get(properties.class_name) ?? 0) + 1);
      }
    }
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

/** Approximate length × width in metres of an (oriented) box polygon in lon/lat. */
export function boxSizeMetres(ring: number[][]): [number, number] {
  if (ring.length < 3) return [0, 0];
  const lat = ring[0][1];
  const metres = (a: number[], b: number[]) => {
    const dx = (b[0] - a[0]) * 111_320 * Math.cos((lat * Math.PI) / 180);
    const dy = (b[1] - a[1]) * 110_574;
    return Math.hypot(dx, dy);
  };
  const sides = [metres(ring[0], ring[1]), metres(ring[1], ring[2])];
  return [Math.max(...sides), Math.min(...sides)];
}

/** [west, south, east, north] of a polygon ring. */
export function ringBounds(ring: number[][]): [number, number, number, number] {
  const lons = ring.map((p) => p[0]);
  const lats = ring.map((p) => p[1]);
  return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
}
