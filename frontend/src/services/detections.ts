import type { Feature, FeatureCollection, Polygon } from "geojson";
import { api } from "./health";

export interface DetectionProperties {
  class_name: string;
  class_id: number;
  confidence: number;
  job_id: string;
  image_id: string;
  pixel_bbox: { points: number[][]; clipped_to_image?: boolean };
}

export type DetectionFeature = Feature<Polygon, DetectionProperties>;
export type DetectionCollection = FeatureCollection<Polygon, DetectionProperties>;

/** Detections of the image's latest completed detection job (GeoJSON, EPSG:4326). */
export async function getDetections(imageId: string): Promise<DetectionCollection> {
  const response = await api.get<DetectionCollection>(`/api/v1/images/${imageId}/detections`, {
    params: { limit: 10_000 },
  });
  return response.data;
}
