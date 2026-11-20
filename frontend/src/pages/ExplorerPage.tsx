import { useQueries, useQuery } from "@tanstack/react-query";
import type { LngLat } from "maplibre-gl";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import MetadataPanel from "../components/imagery/MetadataPanel";
import AnalyzeButton from "../components/jobs/AnalyzeButton";
import DetectionsPanel from "../components/map/DetectionsPanel";
import { visibleDetections } from "../components/map/detectionStyle";
import { getDetections, type DetectionCollection } from "../services/detections";
import { apiErrorMessage, getTileJson, listImages, type TileJson } from "../services/images";
import { useExplorerStore } from "../store/explorer";
import { formatLngLat } from "../utils/format";

/** Loaded detection collections; TanStack Query keeps this stable while data is unchanged. */
function loadedCollections(results: { data?: DetectionCollection }[]): DetectionCollection[] {
  return results.flatMap((r) => (r.data ? [r.data] : []));
}

// MapLibre is large; load it only on this page.
const ImageryMap = lazy(() => import("../components/map/ImageryMap"));

export default function ExplorerPage() {
  const { selectedId, hiddenIds, opacity, select, toggleVisible, setOpacity } = useExplorerStore();
  const { showDetections, minConfidence, hiddenClasses } = useExplorerStore();
  const [pointer, setPointer] = useState<LngLat | null>(null);
  const [zoom, setZoom] = useState<number | null>(null);
  // The selected image is part of the URL (/explorer?image=<id>), so views can be linked to.
  const [searchParams, setSearchParams] = useSearchParams();
  const imageParam = searchParams.get("image");
  useEffect(() => {
    select(imageParam);
  }, [imageParam, select]);

  const images = useQuery({ queryKey: ["images"], queryFn: () => listImages(200) });
  const items = useMemo(() => images.data?.items ?? [], [images.data]);
  const visibleIds = useMemo(
    () => items.filter((i) => !hiddenIds[i.id]).map((i) => i.id),
    [items, hiddenIds],
  );

  const tileJsonQueries = useQueries({
    queries: visibleIds.map((id) => ({
      queryKey: ["tilejson", id],
      queryFn: () => getTileJson(id),
      staleTime: Infinity,
    })),
  });
  const tileJsons: Record<string, TileJson> = {};
  visibleIds.forEach((id, i) => {
    const data = tileJsonQueries[i]?.data;
    if (data) tileJsons[id] = data;
  });

  const collections = useQueries({
    queries: visibleIds.map((id) => ({
      queryKey: ["detections", id],
      queryFn: () => getDetections(id),
      staleTime: 30_000,
    })),
    combine: loadedCollections,
  });
  const detections = useMemo(
    () => visibleDetections(showDetections ? collections : [], { minConfidence, hiddenClasses }),
    [collections, showDetections, minConfidence, hiddenClasses],
  );

  return (
    <section className="flex h-full flex-col">
      <h1 className="mb-4 text-2xl font-semibold">Kart</h1>
      <div className="grid flex-1 gap-4 lg:grid-cols-[1fr_340px]">
        <div className="relative h-[60vh] min-h-[400px] overflow-hidden rounded border border-slate-200 lg:h-[calc(100vh-8rem)] dark:border-slate-800">
          <Suspense fallback={<p className="p-4">Laster kart …</p>}>
            <ImageryMap
              images={items}
              visibleIds={visibleIds}
              tileJsons={tileJsons}
              selectedId={selectedId}
              opacity={opacity}
              detections={detections}
              onPointerMove={setPointer}
              onZoomChange={setZoom}
            />
          </Suspense>
          <div
            aria-live="polite"
            className="absolute right-2 bottom-2 rounded bg-white/90 px-2 py-1 font-mono text-xs text-slate-900"
          >
            {pointer ? formatLngLat(pointer.lng, pointer.lat) : "Beveg musen over kartet"}
            {zoom !== null && ` · z${zoom.toFixed(1)}`}
          </div>
        </div>

        <aside className="space-y-4 lg:overflow-y-auto">
          <div>
            <h2 className="mb-2 font-medium">Bildelag</h2>
            {images.isPending && <p role="status">Henter bilder …</p>}
            {images.isError && (
              <p role="alert">Kunne ikke hente bilder: {apiErrorMessage(images.error)}</p>
            )}
            {images.data && items.length === 0 && (
              <p className="text-sm text-slate-500">Ingen bilder. Last opp på «Bilder»-siden.</p>
            )}
            <ul className="space-y-1">
              {items.map((image) => {
                const tileJson = tileJsons[image.id];
                const belowMinZoom = tileJson && zoom !== null && zoom < tileJson.minzoom;
                return (
                  <li
                    key={image.id}
                    className={`flex items-center gap-2 rounded px-2 py-1 text-sm ${
                      selectedId === image.id ? "bg-slate-200 dark:bg-slate-800" : ""
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={!hiddenIds[image.id]}
                      onChange={() => toggleVisible(image.id)}
                      aria-label={`Vis ${image.filename}`}
                    />
                    <button
                      type="button"
                      onClick={() => setSearchParams({ image: image.id })}
                      className="flex-1 truncate text-left hover:underline"
                      title={image.filename}
                    >
                      {image.filename}
                    </button>
                    {belowMinZoom && (
                      <span className="text-xs text-slate-500" title="Zoom inn for å se bildet">
                        z≥{tileJson.minzoom}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>

          <label className="block text-sm">
            <span className="mb-1 block font-medium">
              Synlighet bildelag: {Math.round(opacity * 100)} %
            </span>
            <input
              type="range"
              aria-label="Synlighet bildelag"
              min={0}
              max={1}
              step={0.05}
              value={opacity}
              onChange={(e) => setOpacity(Number(e.target.value))}
              className="w-full"
            />
          </label>

          <DetectionsPanel collections={collections} visible={detections} />

          {selectedId && (
            <div>
              <h2 className="mb-2 font-medium">Analyse</h2>
              <AnalyzeButton imageId={selectedId} />
            </div>
          )}

          {selectedId && (
            <div>
              <h2 className="mb-2 font-medium">Metadata</h2>
              <MetadataPanel imageId={selectedId} />
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
