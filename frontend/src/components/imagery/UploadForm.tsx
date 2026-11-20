import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { apiErrorMessage, uploadImage, type UploadResult } from "../../services/images";
import { toast } from "../../store/toasts";

export default function UploadForm() {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);

  const mutation = useMutation<UploadResult, unknown, File>({
    mutationFn: (selected) => uploadImage(selected, setProgress),
    onSuccess: (result) => {
      toast.success(`${result.filename} er lastet opp og klar.`);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
      void queryClient.invalidateQueries({ queryKey: ["images"] });
      void queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (error) => toast.error(`Opplastingen ble avvist: ${apiErrorMessage(error)}`),
  });

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    setProgress(0);
    mutation.mutate(file);
  }

  return (
    <form
      onSubmit={submit}
      className="mb-6 rounded border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
    >
      <label htmlFor="geotiff" className="mb-2 block font-medium">
        Last opp GeoTIFF
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <input
          id="geotiff"
          ref={inputRef}
          type="file"
          accept=".tif,.tiff,image/tiff"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-sm"
        />
        <button
          type="submit"
          disabled={!file || mutation.isPending}
          className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
        >
          {mutation.isPending ? "Laster opp …" : "Last opp"}
        </button>
      </div>

      {mutation.isPending && (
        <div className="mt-3">
          <progress
            aria-label="Opplasting"
            value={progress}
            max={1}
            className="h-2 w-full max-w-md"
          />
          <p className="text-sm text-slate-500">
            {progress < 1
              ? `${Math.round(progress * 100)} % lastet opp`
              : "Validerer og konverterer til COG …"}
          </p>
        </div>
      )}
      {mutation.isError && (
        <p role="alert" className="mt-3 text-red-700 dark:text-red-400">
          Opplastingen ble avvist: {apiErrorMessage(mutation.error)}
        </p>
      )}
      {mutation.isSuccess && (
        <p role="status" className="mt-3 text-green-700 dark:text-green-400">
          {mutation.data.filename} er lastet opp.
        </p>
      )}
    </form>
  );
}
