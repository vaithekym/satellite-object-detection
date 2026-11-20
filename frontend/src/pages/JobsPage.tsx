import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import JobStatusBadge, { ProgressBar } from "../components/jobs/JobStatusBadge";
import { apiErrorMessage } from "../services/images";
import { cancelJob, isActive, listJobs, type Job } from "../services/jobs";
import { toast } from "../store/toasts";
import { formatDate } from "../utils/format";

function duration(job: Job): string {
  if (!job.started_at) return "–";
  const end = job.completed_at ? new Date(job.completed_at) : new Date();
  const seconds = (end.getTime() - new Date(job.started_at).getTime()) / 1000;
  return `${seconds.toFixed(1)} s`;
}

export default function JobsPage() {
  const queryClient = useQueryClient();
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["jobs", "all"],
    queryFn: () => listJobs(),
    refetchInterval: (query) => (query.state.data?.items.some(isActive) ? 1000 : 10_000),
  });
  const cancel = useMutation({
    mutationFn: cancelJob,
    onSuccess: (job) => {
      toast.info(`Jobben for ${job.image_filename ?? "bildet"} er avbrutt.`);
      return queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (error) => toast.error(`Kunne ikke avbryte: ${apiErrorMessage(error)}`),
  });

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Jobber</h1>
      {isPending && <p role="status">Henter jobber …</p>}
      {isError && (
        <p role="alert" className="text-red-700 dark:text-red-400">
          Kunne ikke hente jobber: {apiErrorMessage(error)}
        </p>
      )}
      {data && data.items.length === 0 && (
        <p className="text-slate-500">
          Ingen jobber ennå. Start en analyse fra kartet ved å velge et bilde.
        </p>
      )}
      {data && data.items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-slate-500 dark:border-slate-800">
              <tr>
                <th className="py-2 pr-3">Jobb</th>
                <th className="pr-3">Bilde</th>
                <th className="pr-3">Type</th>
                <th className="pr-3">Status</th>
                <th className="pr-3">Fremdrift</th>
                <th className="pr-3">Startet</th>
                <th className="pr-3">Fullført</th>
                <th className="pr-3">Varighet</th>
                <th className="pr-3">Melding</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.items.map((job) => (
                <tr key={job.job_id} className="border-b border-slate-100 dark:border-slate-900">
                  <td className="py-2 pr-3 font-mono text-xs" title={job.job_id}>
                    {job.job_id.slice(0, 8)}
                  </td>
                  <td className="pr-3">
                    <Link className="hover:underline" to={`/explorer?image=${job.image_id}`}>
                      {job.image_filename ?? job.image_id.slice(0, 8)}
                    </Link>
                  </td>
                  <td className="pr-3">
                    {job.job_type === "object_detection" ? "Objektdeteksjon" : job.job_type}
                  </td>
                  <td className="pr-3">
                    <JobStatusBadge status={job.status} />
                  </td>
                  <td className="pr-3">
                    <ProgressBar
                      value={job.progress}
                      label={`Fremdrift ${job.job_id.slice(0, 8)}`}
                    />
                  </td>
                  <td className="pr-3">{job.started_at ? formatDate(job.started_at) : "–"}</td>
                  <td className="pr-3">{job.completed_at ? formatDate(job.completed_at) : "–"}</td>
                  <td className="pr-3">{duration(job)}</td>
                  <td className="max-w-xs pr-3">
                    {job.error_message ? (
                      <span className="text-red-700 dark:text-red-400">{job.error_message}</span>
                    ) : (
                      job.message
                    )}
                  </td>
                  <td>
                    {(job.status === "QUEUED" || job.status === "PENDING") && (
                      <button
                        type="button"
                        className="text-xs text-red-700 hover:underline"
                        onClick={() => cancel.mutate(job.job_id)}
                      >
                        Avbryt
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
