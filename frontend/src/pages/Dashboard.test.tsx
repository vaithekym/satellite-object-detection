import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import { getReadiness } from "../services/health";
import { getStats } from "../services/stats";
import Dashboard from "./Dashboard";

vi.mock("../services/health", () => ({ getReadiness: vi.fn() }));
vi.mock("../services/stats", () => ({ getStats: vi.fn() }));
const mockedGetReadiness = vi.mocked(getReadiness);

function renderDashboard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const emptyStats = {
  images: 0,
  analyses_completed: 0,
  jobs_active: 0,
  jobs_failed: 0,
  detections: 0,
  detections_by_class: {},
  recent_activity: [],
};

describe("Dashboard statistics", () => {
  it("shows figures, objects per class and recent activity from the API", async () => {
    vi.mocked(getReadiness).mockResolvedValue({ status: "ready", checks: {} });
    vi.mocked(getStats).mockResolvedValue({
      images: 6,
      analyses_completed: 10,
      jobs_active: 1,
      jobs_failed: 2,
      detections: 440,
      detections_by_class: { plane: 227, "storage tank": 4 },
      recent_activity: [
        {
          kind: "job_failed",
          at: "2026-11-19T22:54:06Z",
          image_id: "img-1",
          image_filename: "naip_san_2022.tif",
          job_id: "job-1",
          message: "RuntimeError: model crashed",
        },
      ],
    });
    renderDashboard();

    const figures = await screen.findByRole("list", { name: "Nøkkeltall" });
    expect(figures).toHaveTextContent("Bilder6");
    expect(figures).toHaveTextContent("Fullførte analyser10");
    expect(figures).toHaveTextContent("Aktive jobber1");
    expect(figures).toHaveTextContent("Feilede jobber2");
    expect(figures).toHaveTextContent("Gjenkjente objekter440");
    const byClass = screen.getByRole("list", { name: "Objekter per type" });
    expect(byClass).toHaveTextContent("Fly227");
    expect(byClass).toHaveTextContent("Lagertank4");
    const activity = screen.getByRole("list", { name: "Siste aktivitet" });
    expect(activity).toHaveTextContent(
      "Analyse feilet: naip_san_2022.tif – RuntimeError: model crashed",
    );
  });

  it("shows empty states without inventing numbers", async () => {
    vi.mocked(getReadiness).mockResolvedValue({ status: "ready", checks: {} });
    vi.mocked(getStats).mockResolvedValue(emptyStats);
    renderDashboard();
    expect(await screen.findByText("Ingen analyser ennå.")).toBeInTheDocument();
    expect(screen.getByText("Ingen aktivitet ennå.")).toBeInTheDocument();
  });
});

// Each test sets its own mock result. Note: calling mockReset() here makes Vitest 5
// report the intentionally rejected promise in the error test as a test failure.
describe("Dashboard system status", () => {
  beforeEach(() => {
    vi.mocked(getStats).mockResolvedValue(emptyStats);
  });

  it("shows all services as ready", async () => {
    mockedGetReadiness.mockResolvedValue({
      status: "ready",
      checks: {
        postgres: { ok: true, detail: "PostGIS 3.7.0" },
        rabbitmq: { ok: true, detail: "connected" },
      },
    });
    renderDashboard();

    expect(await screen.findByText("Alle tjenester er klare.")).toBeInTheDocument();
    expect(screen.getByText("PostgreSQL / PostGIS")).toBeInTheDocument();
    expect(screen.getByText("PostGIS 3.7.0")).toBeInTheDocument();
  });

  it("shows which service is down", async () => {
    mockedGetReadiness.mockResolvedValue({
      status: "not_ready",
      checks: {
        postgres: { ok: true, detail: "PostGIS 3.7.0" },
        rabbitmq: { ok: false, detail: "timed out" },
      },
    });
    renderDashboard();

    expect(await screen.findByText("Én eller flere tjenester er nede.")).toBeInTheDocument();
    expect(screen.getByText("Feil")).toBeInTheDocument();
    expect(screen.getByText("timed out")).toBeInTheDocument();
  });

  it("shows an error when the API is unreachable", async () => {
    mockedGetReadiness.mockRejectedValue(new Error("Network Error"));
    renderDashboard();

    expect(await screen.findByRole("alert")).toHaveTextContent("Får ikke kontakt med API-et");
  });
});
