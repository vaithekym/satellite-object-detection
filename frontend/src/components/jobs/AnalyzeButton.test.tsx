import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { listJobs, startAnalysis, type Job } from "../../services/jobs";
import AnalyzeButton from "./AnalyzeButton";

vi.mock("../../services/jobs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../services/jobs")>();
  return { ...actual, listJobs: vi.fn(), startAnalysis: vi.fn() };
});

const running: Job = {
  job_id: "job-1",
  image_id: "img-1",
  image_filename: "a.tif",
  job_type: "object_detection",
  status: "RUNNING",
  progress: 45,
  message: "Processing image tiles (4/9)",
  error_message: null,
  model_name: null,
  model_version: null,
  parameters: {},
  created_at: "2026-11-19T22:00:00Z",
  started_at: "2026-11-19T22:00:01Z",
  completed_at: null,
};

describe("AnalyzeButton", () => {
  it("starts an analysis", async () => {
    vi.mocked(listJobs).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(startAnalysis).mockResolvedValue({ job_id: "job-1", status: "QUEUED" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AnalyzeButton imageId="img-1" />
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Finn objekter i bildet" }));
    await waitFor(() => expect(vi.mocked(startAnalysis)).toHaveBeenCalledWith("img-1"));
  });

  it("shows progress while running and reloads detections when the job completes", async () => {
    vi.mocked(listJobs).mockResolvedValue({ items: [running], total: 1 });
    const fetchDetections = vi.fn().mockResolvedValue("detections");
    function DetectionsProbe() {
      useQuery({ queryKey: ["detections", "img-1"], queryFn: fetchDetections });
      return null;
    }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AnalyzeButton imageId="img-1" />
        <DetectionsProbe />
      </QueryClientProvider>,
    );

    expect(await screen.findByLabelText("Analysefremdrift")).toHaveValue(45);
    expect(screen.getByRole("button", { name: "Analyse pågår …" })).toBeDisabled();
    await waitFor(() => expect(fetchDetections).toHaveBeenCalledTimes(1));

    vi.mocked(listJobs).mockResolvedValue({
      items: [
        { ...running, status: "COMPLETED", progress: 100, message: "Completed: 52 detections" },
      ],
      total: 1,
    });
    // The running job is polled every second; completion triggers a detections reload.
    expect(
      await screen.findByText("Completed: 52 detections", {}, { timeout: 3000 }),
    ).toBeInTheDocument();
    await waitFor(() => expect(fetchDetections).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Finn objekter i bildet" })).toBeEnabled();
  });
});
