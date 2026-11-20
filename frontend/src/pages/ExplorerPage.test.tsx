import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ImageryMapProps } from "../components/map/ImageryMap";
import { getDetections, type DetectionCollection } from "../services/detections";
import { getImage, getTileJson, listImages, type ImageSummary } from "../services/images";
import { useExplorerStore } from "../store/explorer";
import ExplorerPage from "./ExplorerPage";

// MapLibre needs WebGL, which jsdom does not have: render the props instead.
vi.mock("../components/map/ImageryMap", () => ({
  default: (props: ImageryMapProps) => (
    <div data-testid="map">
      visible={props.visibleIds.join(",")} tiles={Object.keys(props.tileJsons).join(",")}
      opacity={props.opacity} detections=
      {props.detections.features
        .map((f) => (f.properties as unknown as { label: string }).label)
        .join("|")}
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
  return { ...actual, listImages: vi.fn(), getImage: vi.fn(), getTileJson: vi.fn() };
});

function image(id: string, filename: string): ImageSummary {
  return {
    id,
    filename,
    file_size: 1000,
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
          [0, 0],
          [1, 0],
          [1, 1],
          [0, 0],
        ],
      ],
    },
    acquisition_date: "2024-05-06T16:00:00Z",
    uploaded_at: "2026-11-19T21:00:00Z",
    processing_status: "READY",
  };
}

const a = image("a", "naip_san_2024.tif");
const b = image("b", "naip_san_2022.tif");

function detectionsFor(imageId: string): DetectionCollection {
  const make = (class_name: string, confidence: number) => ({
    type: "Feature" as const,
    geometry: {
      type: "Polygon" as const,
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
      image_id: imageId,
      pixel_bbox: { points: [] },
    },
  });
  const features =
    imageId === "a"
      ? [make("plane", 0.93), make("plane", 0.3), make("storage tank", 0.72)]
      : [make("plane", 0.88)];
  return { type: "FeatureCollection", features };
}

function renderPage(url = "/explorer") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <ExplorerPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ExplorerPage", () => {
  beforeEach(() => {
    useExplorerStore.setState({
      selectedId: null,
      hiddenIds: {},
      opacity: 1,
      showDetections: true,
      minConfidence: 0.5,
      hiddenClasses: {},
    });
    vi.mocked(getDetections).mockImplementation(async (id) => detectionsFor(id));
    vi.mocked(listImages).mockResolvedValue({ items: [a, b], total: 2 });
    vi.mocked(getTileJson).mockImplementation(async (id) => ({
      tiles: [],
      minzoom: 15,
      maxzoom: 18,
      bounds: [id === "a" ? 1 : 2, 0, 3, 1],
    }));
  });

  it("shows all images as visible layers and loads their tile metadata", async () => {
    renderPage();
    expect(await screen.findByText("visible=a,b tiles=a,b", { exact: false })).toBeInTheDocument();
    expect(screen.getByLabelText("Vis naip_san_2024.tif")).toBeChecked();
  });

  it("hides a layer when it is unchecked", async () => {
    renderPage();
    fireEvent.click(await screen.findByLabelText("Vis naip_san_2022.tif"));
    expect(await screen.findByText("visible=a tiles=a", { exact: false })).toBeInTheDocument();
    expect(screen.getByLabelText("Vis naip_san_2022.tif")).not.toBeChecked();
  });

  it("passes the opacity slider value to the map", async () => {
    renderPage();
    await screen.findByText("visible=a,b", { exact: false });
    fireEvent.change(screen.getByLabelText("Synlighet bildelag"), { target: { value: "0.4" } });
    expect(screen.getByText("Synlighet bildelag: 40 %")).toBeInTheDocument();
    expect(screen.getByTestId("map")).toHaveTextContent("opacity=0.4");
  });

  it("shows metadata for the selected image", async () => {
    vi.mocked(getImage).mockResolvedValue({
      ...a,
      metadata: {
        wgs84_bbox: [-117.200071, 32.728951, -117.186936, 32.740056],
        color_interpretation: ["red", "green", "blue", "undefined"],
        dtypes: ["uint8", "uint8", "uint8", "uint8"],
        nodata: null,
        acquisition_date_source: "ACQUISITIONDATETIME",
      },
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "naip_san_2024.tif" }));

    expect(await screen.findByText("EPSG:26911")).toBeInTheDocument();
    expect(screen.getByText("-117.20007, 32.72895, -117.18694, 32.74006")).toBeInTheDocument();
    expect(screen.getByText("4 (red, green, blue, undefined)")).toBeInTheDocument();
    expect(screen.getByText("ACQUISITIONDATETIME")).toBeInTheDocument();
    expect(vi.mocked(getImage)).toHaveBeenCalledWith("a");
  });

  it("selects the image given in the URL", async () => {
    vi.mocked(getImage).mockResolvedValue({ ...b, metadata: {} });
    renderPage("/explorer?image=b");
    expect(await screen.findByText("EPSG:26911")).toBeInTheDocument();
    expect(useExplorerStore.getState().selectedId).toBe("b");
    expect(vi.mocked(getImage)).toHaveBeenCalledWith("b");
  });

  it("shows detected objects on the map with labels, above the default 50 % confidence", async () => {
    renderPage();
    expect(
      await screen.findByText("detections=Fly 93 %|Lagertank 72 %|Fly 88 %", { exact: false }),
    ).toBeInTheDocument();
    const legend = screen.getByRole("list", { name: "Objekttyper" });
    expect(legend).toHaveTextContent("Fly2");
    expect(legend).toHaveTextContent("Lagertank1");
  });

  it("filters objects by confidence and by class", async () => {
    renderPage();
    await screen.findByText("Lagertank 72 %", { exact: false });

    fireEvent.change(screen.getByLabelText("Minste konfidens"), { target: { value: "0.2" } });
    expect(
      await screen.findByText("detections=Fly 93 %|Fly 30 %|Lagertank 72 %|Fly 88 %", {
        exact: false,
      }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Vis Fly"));
    expect(
      await screen.findByText("detections=Lagertank 72 %", { exact: false }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Vis gjenkjente objekter"));
    expect(screen.getByTestId("map").textContent).toMatch(/detections=\s*$/);
  });

  it("only shows objects for visible images", async () => {
    renderPage();
    await screen.findByText("Fly 88 %", { exact: false });
    fireEvent.click(screen.getByLabelText("Vis naip_san_2024.tif"));
    expect(await screen.findByText("detections=Fly 88 %", { exact: false })).toBeInTheDocument();
  });

  it("shows an empty state when there are no images", async () => {
    vi.mocked(listImages).mockResolvedValue({ items: [], total: 0 });
    renderPage();
    expect(await screen.findByText(/Ingen bilder/)).toBeInTheDocument();
  });
});
