import type { DetectionCollection } from "../../services/detections";
import { useExplorerStore } from "../../store/explorer";
import { toast } from "../../store/toasts";
import { downloadGeoJson, exportableDetections } from "../../utils/download";
import { classColor, classLabel, countByClass } from "./detectionStyle";

/** Detection filters and colour legend with per-class counts. */
interface DetectionsPanelProps {
  collections: DetectionCollection[];
  /** The filtered detections currently shown on the map (what gets exported). */
  visible: DetectionCollection;
}

export default function DetectionsPanel({ collections, visible }: DetectionsPanelProps) {
  const { showDetections, minConfidence, hiddenClasses } = useExplorerStore();
  const { setShowDetections, setMinConfidence, toggleClass } = useExplorerStore();
  const counts = countByClass(collections, minConfidence);
  const total = collections.reduce((sum, c) => sum + c.features.length, 0);

  return (
    <div>
      <h2 className="mb-2 font-medium">Objekter</h2>
      <label className="mb-2 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={showDetections}
          onChange={(e) => setShowDetections(e.target.checked)}
        />
        Vis gjenkjente objekter
      </label>

      <label className="mb-2 block text-sm">
        <span className="mb-1 block">Minste konfidens: {Math.round(minConfidence * 100)} %</span>
        <input
          type="range"
          aria-label="Minste konfidens"
          min={0}
          max={1}
          step={0.05}
          value={minConfidence}
          onChange={(e) => setMinConfidence(Number(e.target.value))}
          className="w-full"
        />
      </label>

      {total === 0 ? (
        <p className="text-sm text-slate-500">
          Ingen analyserte bilder i visningen. Velg et bilde og trykk «Finn objekter i bildet».
        </p>
      ) : counts.length === 0 ? (
        <p className="text-sm text-slate-500">Ingen objekter over valgt konfidens.</p>
      ) : (
        <ul className="space-y-1 text-sm" aria-label="Objekttyper">
          {counts.map(([className, count]) => (
            <li key={className}>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={!hiddenClasses[className]}
                  onChange={() => toggleClass(className)}
                  aria-label={`Vis ${classLabel(className)}`}
                />
                <span
                  aria-hidden
                  className="inline-block h-3 w-3 rounded-sm border-2"
                  style={{ borderColor: classColor(className) }}
                />
                <span className="flex-1">{classLabel(className)}</span>
                <span className="text-slate-500">{count}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        disabled={visible.features.length === 0}
        onClick={() => {
          const date = new Date().toISOString().slice(0, 10);
          downloadGeoJson(exportableDetections(visible), `objekter-${date}.geojson`);
          toast.success(`Eksporterte ${visible.features.length} objekter som GeoJSON.`);
        }}
        className="mt-3 rounded border border-slate-300 px-3 py-1.5 text-sm disabled:opacity-50 dark:border-slate-700"
      >
        Eksporter GeoJSON ({visible.features.length})
      </button>
      <p className="mt-2 text-xs text-slate-500">
        Klikk på et objekt i kartet for detaljer. Konfidens er modellens poengsum, ikke en
        sannsynlighet for at treffet er riktig.
      </p>
    </div>
  );
}
