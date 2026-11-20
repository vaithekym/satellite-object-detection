import { describe, expect, it } from "vitest";
import { exportableDetections } from "./download";

describe("exportableDetections", () => {
  it("keeps geometry and data properties but drops the map-only label", () => {
    const geometry = { type: "Point" as const, coordinates: [10, 60] };
    const result = exportableDetections({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          id: "d1",
          geometry,
          properties: { class_name: "plane", confidence: 0.9, label: "Fly 90 %" },
        },
      ],
    });
    expect(result.features[0]).toEqual({
      type: "Feature",
      id: "d1",
      geometry,
      properties: { class_name: "plane", confidence: 0.9 },
    });
  });
});
