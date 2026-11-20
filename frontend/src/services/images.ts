import { isAxiosError } from "axios";
import { api } from "./health";

export interface GeoJsonPolygon {
  type: "Polygon";
  coordinates: number[][][];
}

export interface ImageSummary {
  id: string;
  filename: string;
  file_size: number;
  width: number;
  height: number;
  band_count: number;
  crs: string;
  resolution_x: number;
  resolution_y: number;
  resolution_unit: string | null;
  bounds: GeoJsonPolygon;
  acquisition_date: string | null;
  uploaded_at: string;
  processing_status: string;
}

export interface ImageList {
  items: ImageSummary[];
  total: number;
}

export interface UploadResult {
  id: string;
  filename: string;
  status: string;
}

export async function listImages(limit = 50, offset = 0): Promise<ImageList> {
  const response = await api.get<ImageList>("/api/v1/images", { params: { limit, offset } });
  return response.data;
}

export async function uploadImage(
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await api.post<UploadResult>("/api/v1/images/upload", form, {
    timeout: 0, // large files; the server enforces its own limits
    onUploadProgress: (event) => {
      if (onProgress && event.total) onProgress(event.loaded / event.total);
    },
  });
  return response.data;
}

export interface ImageDetail extends ImageSummary {
  metadata: Record<string, unknown>;
}

export interface TileJson {
  tiles: string[];
  minzoom: number;
  maxzoom: number;
  bounds: [number, number, number, number];
}

export async function getImage(imageId: string): Promise<ImageDetail> {
  const response = await api.get<ImageDetail>(`/api/v1/images/${imageId}`);
  return response.data;
}

export async function getTileJson(imageId: string): Promise<TileJson> {
  const response = await api.get<TileJson>(`/api/v1/images/${imageId}/tilejson.json`);
  return response.data;
}

export function previewUrl(imageId: string): string {
  return `/api/v1/images/${imageId}/preview`;
}

/** Same-origin tile URL template (requests go through the dev proxy / reverse proxy). */
export function tileUrlTemplate(imageId: string, origin = window.location.origin): string {
  return `${origin}/api/v1/images/${imageId}/tiles/{z}/{x}/{y}.png`;
}

/** The API's `detail` message when present, otherwise a generic message. */
export function apiErrorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    const detail: unknown = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (!error.response) return "Får ikke kontakt med API-et.";
  }
  return "Noe gikk galt.";
}
