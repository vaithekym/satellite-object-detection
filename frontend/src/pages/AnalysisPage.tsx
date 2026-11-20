import { useQueries, useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import AnalyzeButton from "../components/jobs/AnalyzeButton";
import DetectionsPanel from "../components/map/DetectionsPanel";
import {
  boxSizeMetres,
  classColor,
  classLabel,
  ringBounds,
  visibleDetections,
} from "../components/map/detectionStyle";
import { getDetections, type DetectionFeature } from "../services/detections";
import { apiErrorMessage, getTileJson, listImages, type TileJson } from "../services/images";
import { useExplorerStore } from "../store/explorer";
import { formatLngLat } from "../utils/format";

const ImageryMap = lazy(() => import("../components/map/ImageryMap"));
const TABLE_LIMIT = 200;

export default function AnalysisPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const imageId = searchParams.get("image");
  const { minConfidence, hiddenClasses, showDetections } = useExplorerStore();
  const [focus, setFocus] = useState<{
    key: string;
    bounds: [number, number, number, number];
  } | null>(null);

  const images = useQuery({ queryKey: ["images"], queryFn: () => listImages(200) });
  const items = useMemo(() => images.data?.items ?? [], [images.data]);
  const image = items.find((i) => i.id === imageId) ?? null;

  const [tileJson, detections] = useQueries({
    queries: [
      {
        queryKey: ["tilejson", imageId],
        queryFn: () => getTileJson(imageId!),
        enabled: !!imageId,
        staleTime: Infinity,
      },
      {
        queryKey: ["detections", imageId],
        queryFn: () => getDetections(imageId!),
        enabled: !!imageId,
        staleTime: 30_000,
      },
    ],
  });

  const collections = useMemo(() => (detections.data ? [detections.data] : []), [detections.data]);
  const visible = useMemo(
    () => visibleDetections(showDetections ? collections : [], { minConfidence, hiddenClasses }),
    [collections, showDetections, minConfidence, hiddenClasses],
  );
  const rows = visible.features as DetectionFeature[];
  // Stable props for the map, so it only updates its layers when something changed.
  const mapImages = useMemo(() => (image ? [image] : []), [image]);
  const visibleIds = useMemo(() => (imageId ? [imageId] : []), [imageId]);
  const tileJsons = useMemo<Record<string, TileJson>>(
    () => (imageId && tileJson.data ? { [imageId]: tileJson.data } : {}),
    [imageId, tileJson.data],
  );

  // Zoom to the image when it is chosen.
  useEffect(() => {
    if (image) {
      setFocus({ key: `image-${image.id}`, bounds: ringBounds(image.bounds.coordinates[0]) });
    }
  }, [image]);

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold">Analyse</h1>

      <div className="flex flex-wrap items-end gap-4">
        <label className="text-sm">
          <span className="mb-1 block font-medium">Bilde</span>
          <select
            value={imageId ?? ""}
            onChange={(e) => setSearchParams(e.target.value ? { image: e.target.value } : {})}
            className="rounded border border-slate-300 bg-white px-2 py-1.5 dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="">Velg et bilde …</option>
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.filename}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Analysetype</span>
          <select
            value="object_detection"
            onChange={() => undefined}
            className="rounded border border-slate-300 bg-white px-2 py-1.5 dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="object_detection">Objektdeteksjon (YOLO OBB, DOTA)</option>
          </select>
        </label>
        {imageId && <AnalyzeButton imageId={imageId} />}
      </div>

      {images.isError && (
        <p role="alert">Kunne ikke hente bilder: {apiErrorMessage(images.error)}</p>
      )}
      {!imageId && <p className="text-slate-500">Velg et bilde for å analysere det.</p>}

      {imageId && (
        <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
          <div className="h-[55vh] min-h-[380px] overflow-hidden rounded border border-slate-200 dark:border-slate-800">
            <Suspense fallback={<p className="p-4">Laster kart …</p>}>
              <ImageryMap
                images={mapImages}
                visibleIds={visibleIds}
                tileJsons={tileJsons}
                selectedId={null}
                opacity={1}
                detections={visible}
                focus={focus}
                highlightedId={focus?.key.startsWith("det-") ? focus.key.slice(4) : null}
                onPointerMove={() => undefined}
                onZoomChange={() => undefined}
              />
            </Suspense>
          </div>
          <aside>
            <DetectionsPanel collections={collections} visible={visible} />
          </aside>
        </div>
      )}

      {imageId && (
        <div>
          <h2 className="mb-2 text-lg font-medium">
            Gjenkjente objekter ({rows.length}
            {rows.length > TABLE_LIMIT ? `, viser de ${TABLE_LIMIT} med høyest konfidens` : ""})
          </h2>
          {detections.isPending && <p role="status">Henter objekter …</p>}
          {detections.data && rows.length === 0 && (
            <p className="text-sm text-slate-500">
              {detections.data.features.length === 0
                ? "Bildet er ikke analysert ennå, eller ingen objekter ble funnet."
                : "Ingen objekter med valgte filtre."}
            </p>
          )}
          {rows.length > 0 && (
            <div className="max-h-96 overflow-y-auto">
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-slate-50 text-slate-500 dark:bg-slate-950">
                  <tr>
                    <th className="py-1 pr-3">Objekt</th>
                    <th className="pr-3">Konfidens</th>
                    <th
                      className="pr-3"
                      title="Størrelsen på den roterte boksen, som har litt margin rundt objektet"
                    >
                      Boksens størrelse (ca.)
                    </th>
                    <th className="pr-3">Posisjon</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, TABLE_LIMIT).map((feature) => {
                    const ring = feature.geometry.coordinates[0];
                    const [length, width] = boxSizeMetres(ring);
                    const [w, s, e, n] = ringBounds(ring);
                    const id = String(feature.id);
                    const selected = focus?.key === `det-${id}`;
                    return (
                      <tr
                        key={id}
                        className={`cursor-pointer border-b border-slate-100 hover:bg-slate-100 dark:border-slate-900 dark:hover:bg-slate-900 ${
                          selected ? "bg-slate-200 dark:bg-slate-800" : ""
                        }`}
                        onClick={() => setFocus({ key: `det-${id}`, bounds: [w, s, e, n] })}
                      >
                        <td className="py-1 pr-3">
                          <span
                            aria-hidden
                            className="mr-2 inline-block h-3 w-3 rounded-sm border-2 align-middle"
                            style={{ borderColor: classColor(feature.properties.class_name) }}
                          />
                          {classLabel(feature.properties.class_name)}
                        </td>
                        <td className="pr-3 tabular-nums">
                          {Math.round(feature.properties.confidence * 100)} %
                        </td>
                        <td className="pr-3 tabular-nums">
                          {length.toFixed(0)} × {width.toFixed(0)} m
                        </td>
                        <td className="pr-3 font-mono text-xs">
                          {formatLngLat((w + e) / 2, (s + n) / 2)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
