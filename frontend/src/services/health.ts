import axios from "axios";

export interface CheckStatus {
  ok: boolean;
  detail: string | null;
}

export interface Readiness {
  status: "ready" | "not_ready";
  checks: Record<string, CheckStatus>;
}

export const api = axios.create({ timeout: 10_000 });

/** 503 is an expected answer (a dependency is down) and still carries the check details. */
export async function getReadiness(): Promise<Readiness> {
  const response = await api.get<Readiness>("/health/ready", {
    validateStatus: (code) => code === 200 || code === 503,
  });
  return response.data;
}
