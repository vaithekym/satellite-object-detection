import { describe, expect, it } from "vitest";
import type { ImageSummary } from "../../services/images";
import { footprintsGeoJson, polygonBounds, rasterSource } from "./layers";

const bounds: ImageSummary["bounds"] = {
  type: "Polygon",
  coordinates: [
    [
      [-117.2001, 32.7289],
      [-117.1869, 32.729],
      [-117.187, 32.7401],
      [-117.2, 32.74],
      [-117.2001, 32.7289],
    ],
  ],
};

describe("map layers", () => {
  it("computes the bounding box of a footprint", () => {
    expect(polygonBounds(bounds)).toEqual([-117.2001, 32.7289, -117.1869, 32.7401]);
  });

  it("builds a same-origin raster source limited to the image bounds and zooms", () => {
    const source = rasterSource("abc", {
      tiles: ["http://127.0.0.1:8000/api/v1/images/abc/tiles/{z}/{x}/{y}.png"],
      minzoom: 15,
      maxzoom: 18,
      bounds: [-117.2, 32.72, -117.18, 32.74],
    });
    expect(source.tiles).toEqual([
      `${window.location.origin}/api/v1/images/abc/tiles/{z}/{x}/{y}.png`,
    ]);
    expect(source).toMatchObject({
      minzoom: 15,
      maxzoom: 18,
      bounds: [-117.2, 32.72, -117.18, 32.74],
    });
  });

  it("turns image footprints into GeoJSON features", () => {
    const image = { id: "abc", filename: "a.tif", bounds } as ImageSummary;
    const collection = footprintsGeoJson([image]);
    expect(collection.features).toHaveLength(1);
    expect(collection.features[0].properties).toEqual({ id: "abc", filename: "a.tif" });
    expect(collection.features[0].geometry).toBe(bounds);
  });
});
