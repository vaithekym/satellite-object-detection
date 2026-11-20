import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { apiErrorMessage } from "../../services/images";
import { isActive, listJobs, startAnalysis } from "../../services/jobs";
import { toast } from "../../store/toasts";
import JobStatusBadge, { ProgressBar } from "./JobStatusBadge";

/** Start object detection for an image and follow the latest job's real progress. */
export default function AnalyzeButton({ imageId }: { imageId: string }) {
  const queryClient = useQueryClient();
  const jobs = useQuery({
    queryKey: ["jobs", { image_id: imageId }],
    queryFn: () => listJobs({ image_id: imageId, limit: 1 }),
    // Poll quickly while a job is active, otherwise not at all.
    refetchInterval: (query) => (query.state.data?.items.some(isActive) ? 1000 : false),
  });
  const latest = jobs.data?.items[0];
  const active = latest !== undefined && isActive(latest);

  const start = useMutation({
    mutationFn: () => startAnalysis(imageId),
    onSuccess: () => {
      toast.info("Analysen er lagt i kø.");
      return queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (error) => toast.error(`Kunne ikke starte analysen: ${apiErrorMessage(error)}`),
  });

  // When a job finishes, load its detections onto the map.
  const previousStatus = useRef(latest?.status);
  useEffect(() => {
    if (previousStatus.current && previousStatus.current !== latest?.status) {
      const name = latest?.image_filename ?? "bildet";
      if (latest?.status === "COMPLETED") {
        toast.success(`Analyse av ${name} fullført. ${latest.message ?? ""}`);
        void queryClient.invalidateQueries({ queryKey: ["detections", imageId] });
        void queryClient.invalidateQueries({ queryKey: ["stats"] });
      } else if (latest?.status === "FAILED") {
        toast.error(`Analyse av ${name} feilet: ${latest.error_message ?? "ukjent feil"}`);
      }
    }
    previousStatus.current = latest?.status;
  }, [latest, imageId, queryClient]);

  return (
    <div className="space-y-2 text-sm">
      <button
        type="button"
        onClick={() => start.mutate()}
        disabled={active || start.isPending}
        className="rounded bg-slate-900 px-3 py-1.5 text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
      >
        {active ? "Analyse pågår …" : "Finn objekter i bildet"}
      </button>
      {start.isError && (
        <p role="alert" className="text-red-700 dark:text-red-400">
          Kunne ikke starte analysen: {apiErrorMessage(start.error)}
        </p>
      )}
      {latest && (
        <div className="flex flex-wrap items-center gap-2" aria-live="polite">
          <JobStatusBadge status={latest.status} />
          {active && <ProgressBar value={latest.progress} label="Analysefremdrift" />}
          <span className="text-xs text-slate-500">
            {latest.status === "FAILED" ? latest.error_message : latest.message}
          </span>
        </div>
      )}
    </div>
  );
}
