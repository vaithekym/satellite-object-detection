import type { FeatureCollection } from "geojson";
import type { RasterSourceSpecification, StyleSpecification } from "maplibre-gl";
import { tileUrlTemplate, type ImageSummary, type TileJson } from "../../services/images";

export const BASEMAP_URL: string =
  import.meta.env.VITE_BASEMAP_URL ?? "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

// Font glyphs for map labels (MapLibre's public demo font server by default).
export const GLYPHS_URL: string =
  import.meta.env.VITE_GLYPHS_URL ?? "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf";

export const baseStyle: StyleSpecification = {
  version: 8,
  glyphs: GLYPHS_URL,
  sources: {
    basemap: {
      type: "raster",
      tiles: [BASEMAP_URL],
      tileSize: 256,
      maxzoom: 19,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "basemap", type: "raster", source: "basemap" }],
};

export const FOOTPRINTS_SOURCE = "footprints";
export const FOOTPRINTS_LINE = "footprints-line";
export const DETECTIONS_SOURCE = "detections";
export const DETECTIONS_FILL = "detections-fill";
export const DETECTIONS_LINE = "detections-line";
export const DETECTIONS_LABEL = "detections-label";

export function imageSourceId(imageId: string): string {
  return `image-${imageId}`;
}

export function rasterSource(imageId: string, tileJson: TileJson): RasterSourceSpecification {
  return {
    type: "raster",
    tiles: [tileUrlTemplate(imageId)],
    tileSize: 256,
    minzoom: tileJson.minzoom,
    maxzoom: tileJson.maxzoom, // MapLibre over-zooms beyond this
    bounds: tileJson.bounds, // no tile requests outside the image
  };
}

export function footprintsGeoJson(images: ImageSummary[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: images.map((image) => ({
      type: "Feature",
      id: image.id,
      properties: { id: image.id, filename: image.filename },
      geometry: image.bounds,
    })),
  };
}

/** [west, south, east, north] of a GeoJSON polygon's outer ring. */
export function polygonBounds(polygon: ImageSummary["bounds"]): [number, number, number, number] {
  const ring = polygon.coordinates[0];
  const lons = ring.map(([lon]) => lon);
  const lats = ring.map(([, lat]) => lat);
  return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)];
}
