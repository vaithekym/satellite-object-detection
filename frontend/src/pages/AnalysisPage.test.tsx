import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ImageryMapProps } from "../components/map/ImageryMap";
import { getDetections, type DetectionCollection } from "../services/detections";
import { getTileJson, listImages, type ImageSummary } from "../services/images";
import { useExplorerStore } from "../store/explorer";
import AnalysisPage from "./AnalysisPage";

vi.mock("../components/map/ImageryMap", () => ({
  default: (props: ImageryMapProps) => (
    <div data-testid="map">
      focus={props.focus?.key ?? "none"} highlighted={props.highlightedId ?? "none"} shown=
      {props.detections.features.length}
    </div>
  ),
}));
vi.mock("../services/detections", () => ({ getDetections: vi.fn() }));
vi.mock("../services/jobs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/jobs")>();
  return { ...actual, listJobs: vi.fn().mockResolvedValue({ items: [], total: 0 }) };
});
vi.mock("../services/images", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/images")>();
  return { ...actual, listImages: vi.fn(), getTileJson: vi.fn() };
});

const image: ImageSummary = {
  id: "img-1",
  filename: "naip_lax_2024.tif",
  file_size: 1,
  width: 2048,
  height: 2048,
  band_count: 4,
  crs: "EPSG:26911",
  resolution_x: 0.6,
  resolution_y: 0.6,
  resolution_unit: "metre",
  bounds: {
    type: "Polygon",
    coordinates: [
      [
        [-118.41, 33.93],
        [-118.4, 33.93],
        [-118.4, 33.94],
        [-118.41, 33.93],
      ],
    ],
  },
  acquisition_date: null,
  uploaded_at: "2026-11-19T22:00:00Z",
  processing_status: "READY",
};

// A 40 m × 20 m box at 33.94° N (1° lon ≈ 92.4 km, 1° lat ≈ 110.6 km there).
const dLon = 40 / (111_320 * Math.cos((33.94 * Math.PI) / 180));
const dLat = 20 / 110_574;
function feature(id: string, class_name: string, confidence: number) {
  const [x, y] = [-118.405, 33.94];
  return {
    type: "Feature" as const,
    id,
    geometry: {
      type: "Polygon" as const,
      coordinates: [
        [
          [x, y],
          [x + dLon, y],
          [x + dLon, y + dLat],
          [x, y + dLat],
          [x, y],
        ],
      ],
    },
    properties: {
      class_name,
      class_id: 0,
      confidence,
      job_id: "j",
      image_id: "img-1",
      pixel_bbox: { points: [] },
    },
  };
}
const detections: DetectionCollection = {
  type: "FeatureCollection",
  features: [feature("d1", "plane", 0.93), feature("d2", "plane", 0.7), feature("d3", "ship", 0.3)],
};

function renderPage(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <AnalysisPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AnalysisPage", () => {
  beforeEach(() => {
    useExplorerStore.setState({ minConfidence: 0.5, hiddenClasses: {}, showDetections: true });
    vi.mocked(listImages).mockResolvedValue({ items: [image], total: 1 });
    vi.mocked(getTileJson).mockResolvedValue({
      tiles: [],
      minzoom: 15,
      maxzoom: 18,
      bounds: [-118.41, 33.93, -118.4, 33.94],
    });
    vi.mocked(getDetections).mockResolvedValue(detections);
  });

  it("asks for an image when none is selected", async () => {
    renderPage("/analysis");
    expect(await screen.findByText("Velg et bilde for å analysere det.")).toBeInTheDocument();
    expect(await screen.findByRole("option", { name: "naip_lax_2024.tif" })).toBeInTheDocument();
  });

  it("lists filtered detections with size and position, and zooms the map to a clicked row", async () => {
    renderPage("/analysis?image=img-1");
    expect(await screen.findByText("Gjenkjente objekter (2)")).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2); // the 30 % ship is below the 50 % default
    expect(within(rows[0]).getByText("Fly")).toBeInTheDocument();
    expect(within(rows[0]).getByText("93 %")).toBeInTheDocument();
    expect(within(rows[0]).getByText("40 × 20 m")).toBeInTheDocument();
    expect(within(rows[0]).getByText(/33\.94\d+° N, 118\.40\d+° V/)).toBeInTheDocument();
    expect(screen.getByTestId("map")).toHaveTextContent("focus=image-img-1");

    fireEvent.click(rows[1]);
    expect(screen.getByTestId("map")).toHaveTextContent("focus=det-d2 highlighted=d2");
  });

  it("updates the table when the confidence filter changes", async () => {
    renderPage("/analysis?image=img-1");
    await screen.findByText("Gjenkjente objekter (2)");
    fireEvent.change(screen.getByLabelText("Minste konfidens"), { target: { value: "0.2" } });
    expect(await screen.findByText("Gjenkjente objekter (3)")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("Skip")).toBeInTheDocument();
  });

  it("explains when an image has not been analysed", async () => {
    vi.mocked(getDetections).mockResolvedValue({ type: "FeatureCollection", features: [] });
    renderPage("/analysis?image=img-1");
    expect(
      await screen.findByText("Bildet er ikke analysert ennå, eller ingen objekter ble funnet."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Eksporter GeoJSON (0)" })).toBeDisabled();
  });
});
