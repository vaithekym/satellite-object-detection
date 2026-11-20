import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it, vi } from "vitest";
import { listImages, uploadImage, type ImageSummary } from "../services/images";
import ImagesPage from "./ImagesPage";

vi.mock("../services/images", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/images")>();
  return { ...actual, listImages: vi.fn(), uploadImage: vi.fn() };
});
const mockedList = vi.mocked(listImages);
const mockedUpload = vi.mocked(uploadImage);

const naip: ImageSummary = {
  id: "cd7ef115-1aec-40a9-89a5-76872ca00f79",
  filename: "naip_san_2024.tif",
  file_size: 12_248_357,
  width: 2048,
  height: 2048,
  band_count: 4,
  crs: "EPSG:26911",
  resolution_x: 0.6,
  resolution_y: 0.6,
  resolution_unit: "metre",
  bounds: { type: "Polygon", coordinates: [] },
  acquisition_date: "2024-05-06T16:00:00Z",
  uploaded_at: "2026-11-19T21:00:00Z",
  processing_status: "READY",
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ImagesPage />
    </QueryClientProvider>,
  );
}

function selectFile(name = "scene.tif") {
  const input = screen.getByLabelText("Last opp GeoTIFF");
  fireEvent.change(input, {
    target: { files: [new File(["II*\0"], name, { type: "image/tiff" })] },
  });
}

describe("ImagesPage", () => {
  it("lists images with their metadata and preview", async () => {
    mockedList.mockResolvedValue({ items: [naip], total: 1 });
    renderPage();

    expect(await screen.findByText("naip_san_2024.tif")).toBeInTheDocument();
    expect(screen.getByText("Bildebibliotek (1)")).toBeInTheDocument();
    expect(screen.getByText("2048 × 2048 px, 4 bånd")).toBeInTheDocument();
    expect(screen.getByText("0.6 m")).toBeInTheDocument();
    expect(screen.getByText("EPSG:26911")).toBeInTheDocument();
    expect(screen.getByText("11.7 MB")).toBeInTheDocument();
    expect(screen.getByAltText("Forhåndsvisning av naip_san_2024.tif")).toHaveAttribute(
      "src",
      `/api/v1/images/${naip.id}/preview`,
    );
  });

  it("shows an empty state", async () => {
    mockedList.mockResolvedValue({ items: [], total: 0 });
    renderPage();
    expect(await screen.findByText(/Ingen bilder ennå/)).toBeInTheDocument();
  });

  it("uploads the selected file and refreshes the library", async () => {
    mockedList.mockResolvedValue({ items: [], total: 0 });
    mockedUpload.mockResolvedValue({ id: naip.id, filename: "scene.tif", status: "READY" });
    renderPage();
    await screen.findByText(/Ingen bilder ennå/);

    selectFile();
    mockedList.mockResolvedValue({ items: [naip], total: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Last opp" }));

    expect(await screen.findByText("scene.tif er lastet opp.")).toBeInTheDocument();
    expect(mockedUpload.mock.calls[0][0].name).toBe("scene.tif");
    expect(await screen.findByText("naip_san_2024.tif")).toBeInTheDocument();
  });

  it("shows the API's reason when an upload is rejected", async () => {
    mockedList.mockResolvedValue({ items: [], total: 0 });
    const response = {
      status: 422,
      statusText: "Unprocessable Content",
      data: { detail: "Raster has no coordinate reference system" },
      headers: {},
      config: { headers: new AxiosHeaders() },
    };
    mockedUpload.mockRejectedValue(
      new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, undefined, response),
    );
    renderPage();
    await screen.findByText(/Ingen bilder ennå/);

    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "Last opp" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Opplastingen ble avvist: Raster has no coordinate reference system",
    );
  });

  it("disables the upload button until a file is selected", async () => {
    mockedList.mockResolvedValue({ items: [], total: 0 });
    renderPage();
    expect(screen.getByRole("button", { name: "Last opp" })).toBeDisabled();
  });
});
