import {
  type GeoJSONSource,
  type LngLat,
  MapLibreMap,
  NavigationControl,
  Popup,
  ScaleControl,
  setWorkerUrl,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useEffect, useRef, useState } from "react";
import type { DetectionCollection, DetectionProperties } from "../../services/detections";
import type { ImageSummary, TileJson } from "../../services/images";
import { classColorExpression, classLabel } from "./detectionStyle";
import {
  DETECTIONS_FILL,
  DETECTIONS_LABEL,
  DETECTIONS_LINE,
  DETECTIONS_SOURCE,
  FOOTPRINTS_LINE,
  FOOTPRINTS_SOURCE,
  baseStyle,
  footprintsGeoJson,
  imageSourceId,
  polygonBounds,
  rasterSource,
} from "./layers";

// MapLibre computes its worker URL at runtime, which bundlers cannot follow; without this,
// GeoJSON layers (footprints, detections) silently fail to load in both dev and build.
setWorkerUrl(maplibreWorkerUrl);

export interface ImageryMapProps {
  images: ImageSummary[];
  visibleIds: string[];
  tileJsons: Record<string, TileJson>;
  selectedId: string | null;
  opacity: number;
  detections: DetectionCollection;
  /** Zoom to these bounds when `key` changes (e.g. a clicked table row). */
  focus?: { key: string; bounds: [number, number, number, number] } | null;
  /** Detection to highlight (matches the `detection_id` property). */
  highlightedId?: string | null;
  onPointerMove: (lngLat: LngLat | null) => void;
  onZoomChange: (zoom: number) => void;
}

export default function ImageryMap(props: ImageryMapProps) {
  const { images, visibleIds, tileJsons, selectedId, opacity, detections } = props;
  const { focus = null, highlightedId = null } = props;
  const { onPointerMove, onZoomChange } = props;
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [loaded, setLoaded] = useState(false);
  const callbacks = useRef({ onPointerMove, onZoomChange });
  callbacks.current = { onPointerMove, onZoomChange };

  // Create the map once.
  useEffect(() => {
    if (!containerRef.current) return;
    const map = new MapLibreMap({
      container: containerRef.current,
      style: baseStyle,
      center: [0, 20],
      zoom: 1.5,
    });
    map.addControl(new NavigationControl(), "top-right");
    map.addControl(new ScaleControl({ unit: "metric" }), "bottom-left");
    // "style.load", not "load": "load" waits for every basemap tile, so a slow or
    // unreachable basemap would otherwise keep the imagery layers from ever being added.
    map.once("style.load", () => {
      map.addSource(FOOTPRINTS_SOURCE, { type: "geojson", data: footprintsGeoJson([]) });
      map.addLayer({
        id: FOOTPRINTS_LINE,
        type: "line",
        source: FOOTPRINTS_SOURCE,
        paint: { "line-color": "#f59e0b", "line-width": 1.5 },
      });
      addDetectionLayers(map);
      setLoaded(true);
    });
    map.on("click", DETECTIONS_FILL, (e) => {
      const feature = e.features?.[0];
      if (!feature) return;
      new Popup({ closeButton: true, maxWidth: "260px" })
        .setLngLat(e.lngLat)
        .setDOMContent(detectionPopup(feature.properties as DetectionProperties))
        .addTo(map);
    });
    map.on("mouseenter", DETECTIONS_FILL, () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", DETECTIONS_FILL, () => (map.getCanvas().style.cursor = ""));
    map.on("mousemove", (e) => callbacks.current.onPointerMove(e.lngLat));
    map.on("mouseout", () => callbacks.current.onPointerMove(null));
    map.on("zoomend", () => callbacks.current.onZoomChange(map.getZoom()));
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Image footprints (always shown, also below an image's minimum zoom).
  useEffect(() => {
    const source = mapRef.current?.getSource<GeoJSONSource>(FOOTPRINTS_SOURCE);
    void source?.setData(footprintsGeoJson(images));
  }, [images, loaded]);

  // Detection outlines and labels (already filtered by the page).
  useEffect(() => {
    const source = mapRef.current?.getSource<GeoJSONSource>(DETECTIONS_SOURCE);
    void source?.setData(detections);
  }, [detections, loaded]);

  // Highlight one detection (thicker outline).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded) return;
    map.setPaintProperty(DETECTIONS_LINE, "line-width", [
      "case",
      ["==", ["get", "detection_id"], highlightedId ?? ""],
      5,
      2,
    ]);
  }, [highlightedId, loaded]);

  // Zoom to a requested area — only when its key changes, not on every new bounds array.
  const focusRef = useRef(focus);
  focusRef.current = focus;
  const focusKey = focus?.key;
  useEffect(() => {
    const target = focusRef.current;
    if (target && mapRef.current) {
      mapRef.current.fitBounds(target.bounds, { padding: 120, maxZoom: 19 });
    }
  }, [focusKey]);

  // Highlight the selected footprint.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded) return;
    map.setPaintProperty(FOOTPRINTS_LINE, "line-width", [
      "case",
      ["==", ["get", "id"], selectedId ?? ""],
      3,
      1.5,
    ]);
  }, [selectedId, loaded]);

  // Imagery raster layers: add visible ones, remove hidden ones, keep opacity in sync.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded) return;
    const wanted = new Set(visibleIds.filter((id) => tileJsons[id]));
    for (const id of wanted) {
      const sourceId = imageSourceId(id);
      if (!map.getSource(sourceId)) {
        map.addSource(sourceId, rasterSource(id, tileJsons[id]));
        map.addLayer({ id: sourceId, type: "raster", source: sourceId }, FOOTPRINTS_LINE);
      }
      map.setPaintProperty(sourceId, "raster-opacity", opacity);
    }
    for (const layer of map.getStyle().layers) {
      if (layer.id.startsWith("image-") && !wanted.has(layer.id.slice("image-".length))) {
        map.removeLayer(layer.id);
        map.removeSource(layer.id);
      }
    }
  }, [visibleIds, tileJsons, opacity, loaded]);

  // Zoom to the selected image.
  useEffect(() => {
    const map = mapRef.current;
    const image = images.find((i) => i.id === selectedId);
    if (!map || !image) return;
    map.fitBounds(polygonBounds(image.bounds), { padding: 40, maxZoom: 18 });
  }, [selectedId, images]);

  return <div ref={containerRef} className="h-full w-full" data-testid="imagery-map" />;
}

function addDetectionLayers(map: MapLibreMap) {
  map.addSource(DETECTIONS_SOURCE, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addLayer({
    id: DETECTIONS_FILL,
    type: "fill",
    source: DETECTIONS_SOURCE,
    paint: { "fill-color": classColorExpression, "fill-opacity": 0.1 },
  });
  map.addLayer({
    id: DETECTIONS_LINE,
    type: "line",
    source: DETECTIONS_SOURCE,
    paint: { "line-color": classColorExpression, "line-width": 2 },
  });
  map.addLayer({
    id: DETECTIONS_LABEL,
    type: "symbol",
    source: DETECTIONS_SOURCE,
    minzoom: 15, // from the zoom where 0.6 m imagery appears; overlapping labels are hidden
    layout: {
      "text-field": ["get", "label"],
      "text-font": ["Open Sans Semibold"],
      "text-size": 13,
      "text-anchor": "bottom",
      "text-offset": [0, -0.6],
      "text-allow-overlap": false,
    },
    paint: {
      "text-color": "#0f172a",
      "text-halo-color": "#ffffff",
      "text-halo-width": 2,
    },
  });
}

/** Popup content built from DOM nodes (no HTML injection from data). */
function detectionPopup(properties: DetectionProperties): HTMLElement {
  const root = document.createElement("div");
  root.className = "text-sm text-slate-900";
  const rows: [string, string][] = [
    ["Objekt", classLabel(properties.class_name)],
    ["Modellklasse", properties.class_name],
    ["Konfidens", `${Math.round(properties.confidence * 100)} %`],
  ];
  for (const [key, value] of rows) {
    const line = document.createElement("div");
    const label = document.createElement("strong");
    label.textContent = `${key}: `;
    line.append(label, value);
    root.append(line);
  }
  const note = document.createElement("div");
  note.className = "mt-1 text-xs text-slate-500";
  note.textContent =
    "Konfidens er modellens poengsum, ikke en sannsynlighet for at treffet er riktig.";
  root.append(note);
  return root;
}
