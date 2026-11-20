import { describe, expect, it } from "vitest";
import type { DetectionCollection, DetectionFeature } from "../../services/detections";
import {
  boxSizeMetres,
  classColor,
  classLabel,
  countByClass,
  ringBounds,
  visibleDetections,
} from "./detectionStyle";

function feature(class_name: string, confidence: number): DetectionFeature {
  return {
    type: "Feature",
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [0, 0],
          [1, 0],
          [1, 1],
          [0, 0],
        ],
      ],
    },
    properties: {
      class_name,
      class_id: 0,
      confidence,
      job_id: "j",
      image_id: "i",
      pixel_bbox: { points: [] },
    },
  };
}

const collections: DetectionCollection[] = [
  { type: "FeatureCollection", features: [feature("plane", 0.93), feature("plane", 0.3)] },
  { type: "FeatureCollection", features: [feature("small vehicle", 0.6), feature("ship", 0.8)] },
];

describe("detection styling and filtering", () => {
  it("uses Norwegian labels and per-class colours, with fallbacks", () => {
    expect(classLabel("plane")).toBe("Fly");
    expect(classLabel("storage tank")).toBe("Lagertank");
    expect(classLabel("unknown thing")).toBe("unknown thing");
    expect(classColor("plane")).not.toBe(classColor("ship"));
    expect(classColor("unknown thing")).toBe("#94a3b8");
  });

  it("merges images, filters by confidence and hidden classes, and adds map labels", () => {
    const result = visibleDetections(collections, {
      minConfidence: 0.5,
      hiddenClasses: { ship: true },
    });
    const labels = result.features.map((f) => (f.properties as unknown as { label: string }).label);
    expect(labels).toEqual(["Fly 93 %", "Liten bil 60 %"]);
  });

  it("counts detections per class above the threshold, most frequent first", () => {
    expect(countByClass(collections, 0.5)).toEqual([
      ["plane", 1],
      ["small vehicle", 1],
      ["ship", 1],
    ]);
    expect(countByClass(collections, 0)).toEqual([
      ["plane", 2],
      ["small vehicle", 1],
      ["ship", 1],
    ]);
  });

  it("measures oriented boxes in metres and computes ring bounds", () => {
    const lat = 33.94;
    const dLon = 40 / (111_320 * Math.cos((lat * Math.PI) / 180));
    const dLat = 20 / 110_574;
    // Rotated by listing a short side first: size is still reported long × short.
    const ring = [
      [0, lat],
      [0, lat + dLat],
      [dLon, lat + dLat],
      [dLon, lat],
      [0, lat],
    ];
    const [length, width] = boxSizeMetres(ring);
    expect(length).toBeCloseTo(40, 1);
    expect(width).toBeCloseTo(20, 1);
    expect(ringBounds(ring)).toEqual([0, lat, dLon, lat + dLat]);
  });
});
