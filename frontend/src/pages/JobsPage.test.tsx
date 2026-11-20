import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { cancelJob, listJobs, type Job } from "../services/jobs";
import JobsPage from "./JobsPage";

vi.mock("../services/jobs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/jobs")>();
  return { ...actual, listJobs: vi.fn(), cancelJob: vi.fn() };
});

function job(overrides: Partial<Job>): Job {
  return {
    job_id: "aaaaaaaa-0000-0000-0000-000000000000",
    image_id: "img-1",
    image_filename: "naip_lax_2024.tif",
    job_type: "object_detection",
    status: "COMPLETED",
    progress: 100,
    message: "Completed: 52 detections",
    error_message: null,
    model_name: "yolo26s-obb",
    model_version: "sha256:38dbd72ef680",
    parameters: {},
    created_at: "2026-11-19T22:00:00Z",
    started_at: "2026-11-19T22:00:01Z",
    completed_at: "2026-11-19T22:00:03.600Z",
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <JobsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("JobsPage", () => {
  it("shows job status, real progress, duration and errors", async () => {
    vi.mocked(listJobs).mockResolvedValue({
      total: 3,
      items: [
        job({}),
        job({
          job_id: "bbbbbbbb-0000-0000-0000-000000000000",
          status: "RUNNING",
          progress: 45,
          message: "Processing image tiles (4/9)",
          completed_at: null,
        }),
        job({
          job_id: "cccccccc-0000-0000-0000-000000000000",
          status: "FAILED",
          progress: 5,
          error_message: "ClientError: Not Found",
        }),
      ],
    });
    renderPage();

    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(4); // header + 3 jobs
    expect(within(rows[1]).getByText("Fullført")).toBeInTheDocument();
    expect(within(rows[1]).getByText("2.6 s")).toBeInTheDocument();
    expect(within(rows[1]).getByRole("link", { name: "naip_lax_2024.tif" })).toHaveAttribute(
      "href",
      "/explorer?image=img-1",
    );
    expect(within(rows[2]).getByText("Kjører")).toBeInTheDocument();
    expect(within(rows[2]).getByLabelText("Fremdrift bbbbbbbb")).toHaveValue(45);
    expect(within(rows[2]).getByText("Processing image tiles (4/9)")).toBeInTheDocument();
    expect(within(rows[3]).getByText("ClientError: Not Found")).toBeInTheDocument();
  });

  it("can cancel a queued job", async () => {
    vi.mocked(listJobs).mockResolvedValue({
      total: 1,
      items: [job({ status: "QUEUED", progress: 0, started_at: null, completed_at: null })],
    });
    vi.mocked(cancelJob).mockResolvedValue(job({ status: "CANCELLED" }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Avbryt" }));
    await waitFor(() => expect(vi.mocked(cancelJob)).toHaveBeenCalled());
    expect(vi.mocked(cancelJob).mock.calls[0][0]).toBe("aaaaaaaa-0000-0000-0000-000000000000");
  });

  it("shows an empty state", async () => {
    vi.mocked(listJobs).mockResolvedValue({ total: 0, items: [] });
    renderPage();
    expect(await screen.findByText(/Ingen jobber ennå/)).toBeInTheDocument();
  });
});
