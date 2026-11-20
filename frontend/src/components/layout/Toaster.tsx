import { useToasts, type ToastKind } from "../../store/toasts";

const STYLES: Record<ToastKind, string> = {
  success: "border-green-600 bg-green-50 text-green-900",
  error: "border-red-600 bg-red-50 text-red-900",
  info: "border-slate-400 bg-white text-slate-900",
};

export default function Toaster() {
  const { toasts, dismiss } = useToasts();
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-80 flex-col gap-2"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role={t.kind === "error" ? "alert" : "status"}
          className={`pointer-events-auto flex items-start gap-2 rounded border-l-4 p-3 text-sm shadow ${STYLES[t.kind]}`}
        >
          <span className="flex-1">{t.message}</span>
          <button
            type="button"
            aria-label="Lukk varsel"
            onClick={() => dismiss(t.id)}
            className="text-slate-500 hover:text-slate-900"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
