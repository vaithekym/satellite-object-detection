import type { FeatureCollection } from "geojson";

/** Save a GeoJSON FeatureCollection (RFC 7946, EPSG:4326) as a file in the browser. */
export function downloadGeoJson(collection: FeatureCollection, filename: string): void {
  const blob = new Blob([JSON.stringify(collection, null, 2)], { type: "application/geo+json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Remove display-only properties (the map label) before export. */
export function exportableDetections(collection: FeatureCollection): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: collection.features.map((feature) => {
      const properties: Record<string, unknown> = { ...feature.properties };
      delete properties.label;
      return { ...feature, properties };
    }),
  };
}
