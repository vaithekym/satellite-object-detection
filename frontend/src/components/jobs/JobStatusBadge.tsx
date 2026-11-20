import type { JobStatus } from "../../services/jobs";

const STYLES: Record<JobStatus, { label: string; className: string }> = {
  PENDING: { label: "Venter", className: "bg-slate-200 text-slate-800" },
  QUEUED: { label: "I kø", className: "bg-slate-200 text-slate-800" },
  RUNNING: { label: "Kjører", className: "bg-blue-100 text-blue-800" },
  COMPLETED: { label: "Fullført", className: "bg-green-100 text-green-800" },
  FAILED: { label: "Feilet", className: "bg-red-100 text-red-800" },
  CANCELLED: { label: "Avbrutt", className: "bg-amber-100 text-amber-800" },
};

export default function JobStatusBadge({ status }: { status: JobStatus }) {
  const style = STYLES[status];
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${style.className}`}>
      {style.label}
    </span>
  );
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <progress aria-label={label} value={value} max={100} className="h-2 w-24" />
      <span className="text-xs text-slate-500">{value} %</span>
    </div>
  );
}
