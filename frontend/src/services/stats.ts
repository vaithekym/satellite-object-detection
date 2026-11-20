import { api } from "./health";

export interface Activity {
  kind: "upload" | "job_completed" | "job_failed" | "job_cancelled" | "job_queued";
  at: string;
  image_id: string;
  image_filename: string;
  job_id: string | null;
  message: string | null;
}

export interface Stats {
  images: number;
  analyses_completed: number;
  jobs_active: number;
  jobs_failed: number;
  detections: number;
  detections_by_class: Record<string, number>;
  recent_activity: Activity[];
}

export async function getStats(): Promise<Stats> {
  const response = await api.get<Stats>("/api/v1/stats");
  return response.data;
}
