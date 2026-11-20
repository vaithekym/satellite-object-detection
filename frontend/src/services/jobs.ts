import { isAxiosError } from "axios";
import { api } from "./health";

export type JobStatus = "PENDING" | "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";

export interface Job {
  job_id: string;
  image_id: string;
  image_filename: string | null;
  job_type: string;
  status: JobStatus;
  progress: number;
  message: string | null;
  error_message: string | null;
  model_name: string | null;
  model_version: string | null;
  parameters: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface JobList {
  items: Job[];
  total: number;
}

export const ACTIVE_STATUSES: JobStatus[] = ["PENDING", "QUEUED", "RUNNING"];

export function isActive(job: Job): boolean {
  return ACTIVE_STATUSES.includes(job.status);
}

/** Queue object detection. If one is already active for the image, returns that job's id. */
export async function startAnalysis(imageId: string): Promise<{ job_id: string; status: string }> {
  try {
    const response = await api.post<{ job_id: string; status: string }>("/api/v1/analysis", {
      image_id: imageId,
      analysis_type: "object_detection",
      model: "default",
    });
    return response.data;
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 409) {
      return { job_id: error.response.data.job_id as string, status: "QUEUED" };
    }
    throw error;
  }
}

export async function listJobs(
  params: { image_id?: string; limit?: number } = {},
): Promise<JobList> {
  const response = await api.get<JobList>("/api/v1/jobs", { params: { limit: 100, ...params } });
  return response.data;
}

export async function cancelJob(jobId: string): Promise<Job> {
  const response = await api.post<Job>(`/api/v1/jobs/${jobId}/cancel`);
  return response.data;
}
