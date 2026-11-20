import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { classColor, classLabel } from "../components/map/detectionStyle";
import { getReadiness } from "../services/health";
import { apiErrorMessage } from "../services/images";
import { getStats, type Activity } from "../services/stats";
import { formatDate } from "../utils/format";

const labels: Record<string, string> = {
  postgres: "PostgreSQL / PostGIS",
  rabbitmq: "RabbitMQ",
  object_storage: "Objektlagring (MinIO)",
};

const ACTIVITY_TEXT: Record<Activity["kind"], string> = {
  upload: "Lastet opp",
  job_completed: "Analyse fullført",
  job_failed: "Analyse feilet",
  job_cancelled: "Analyse avbrutt",
  job_queued: "Analyse startet",
};

function StatTile({ label, value, to }: { label: string; value: number; to?: string }) {
  const content = (
    <>
      <div className="text-sm text-slate-500">{label}</div>
      <div className="text-2xl font-semibold">{value.toLocaleString("nb-NO")}</div>
    </>
  );
  const className =
    "block rounded border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900";
  return to ? (
    <Link to={to} className={`${className} hover:border-slate-400`}>
      {content}
    </Link>
  ) : (
    <div className={className}>{content}</div>
  );
}

export default function Dashboard() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: getStats, refetchInterval: 10_000 });
  return (
    <section className="space-y-8">
      <h1 className="text-2xl font-semibold">Oversikt</h1>

      {stats.isPending && <p role="status">Henter statistikk …</p>}
      {stats.isError && (
        <p role="alert" className="text-red-700 dark:text-red-400">
          Kunne ikke hente statistikk: {apiErrorMessage(stats.error)}
        </p>
      )}
      {stats.data && (
        <>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" aria-label="Nøkkeltall">
            <li>
              <StatTile label="Bilder" value={stats.data.images} to="/images" />
            </li>
            <li>
              <StatTile
                label="Fullførte analyser"
                value={stats.data.analyses_completed}
                to="/jobs"
              />
            </li>
            <li>
              <StatTile label="Aktive jobber" value={stats.data.jobs_active} to="/jobs" />
            </li>
            <li>
              <StatTile label="Feilede jobber" value={stats.data.jobs_failed} to="/jobs" />
            </li>
            <li>
              <StatTile label="Gjenkjente objekter" value={stats.data.detections} to="/explorer" />
            </li>
          </ul>

          <div className="grid gap-8 lg:grid-cols-2">
            <div>
              <h2 className="mb-2 text-lg font-medium">Objekter per type</h2>
              {stats.data.detections === 0 ? (
                <p className="text-sm text-slate-500">Ingen analyser ennå.</p>
              ) : (
                <ul className="space-y-1 text-sm" aria-label="Objekter per type">
                  {Object.entries(stats.data.detections_by_class).map(([name, count]) => (
                    <li key={name} className="flex items-center gap-2">
                      <span
                        aria-hidden
                        className="inline-block h-3 w-3 rounded-sm"
                        style={{ background: classColor(name) }}
                      />
                      <span className="flex-1">{classLabel(name)}</span>
                      <span className="tabular-nums">{count}</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-xs text-slate-500">
                Fra siste fullførte analyse av hvert bilde, alle konfidensnivåer.
              </p>
            </div>

            <div>
              <h2 className="mb-2 text-lg font-medium">Siste aktivitet</h2>
              {stats.data.recent_activity.length === 0 ? (
                <p className="text-sm text-slate-500">Ingen aktivitet ennå.</p>
              ) : (
                <ul className="space-y-1 text-sm" aria-label="Siste aktivitet">
                  {stats.data.recent_activity.map((a) => (
                    <li key={`${a.kind}-${a.job_id ?? a.image_id}-${a.at}`} className="flex gap-2">
                      <span className="w-36 shrink-0 text-slate-500">{formatDate(a.at)}</span>
                      <span
                        className={a.kind === "job_failed" ? "text-red-700 dark:text-red-400" : ""}
                      >
                        {ACTIVITY_TEXT[a.kind]}:{" "}
                        <Link className="hover:underline" to={`/explorer?image=${a.image_id}`}>
                          {a.image_filename}
                        </Link>
                        {a.message && <span className="text-slate-500"> – {a.message}</span>}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}

      <SystemStatus />
    </section>
  );
}

function SystemStatus() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["readiness"],
    queryFn: getReadiness,
    refetchInterval: 10_000,
  });

  return (
    <div>
      <h2 className="mb-2 text-lg font-medium">Systemstatus</h2>

      {isPending && <p role="status">Sjekker tjenester …</p>}

      {isError && (
        <p role="alert" className="text-red-700 dark:text-red-400">
          Får ikke kontakt med API-et. Kjører backend (`make backend`)?
        </p>
      )}

      {data && (
        <>
          <p className="mb-3">
            {data.status === "ready"
              ? "Alle tjenester er klare."
              : "Én eller flere tjenester er nede."}
          </p>
          <ul className="grid gap-2 sm:grid-cols-3">
            {Object.entries(data.checks).map(([name, check]) => (
              <li
                key={name}
                className="rounded border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900"
              >
                <div className="font-medium">{labels[name] ?? name}</div>
                <div
                  className={
                    check.ok
                      ? "text-green-700 dark:text-green-400"
                      : "text-red-700 dark:text-red-400"
                  }
                >
                  {check.ok ? "OK" : "Feil"}
                </div>
                {check.detail && <div className="text-sm text-slate-500">{check.detail}</div>}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
