import { useQuery } from "@tanstack/react-query";
import { apiErrorMessage, getImage } from "../../services/images";
import { formatBytes, formatDate, formatResolution } from "../../utils/format";

function value(v: unknown): string {
  if (v === null || v === undefined || v === "") return "–";
  if (Array.isArray(v)) return v.map((x) => value(x)).join(", ");
  return String(v);
}

export default function MetadataPanel({ imageId }: { imageId: string }) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["image", imageId],
    queryFn: () => getImage(imageId),
  });

  if (isPending) return <p role="status">Henter metadata …</p>;
  if (isError) return <p role="alert">Kunne ikke hente metadata: {apiErrorMessage(error)}</p>;

  const m = data.metadata;
  const bbox = (m.wgs84_bbox as number[] | undefined)?.map((v) => v.toFixed(5)).join(", ");
  const rows: [string, string][] = [
    ["Fil", `${data.filename} (${formatBytes(data.file_size)})`],
    ["Størrelse", `${data.width} × ${data.height} px`],
    ["Bånd", `${data.band_count} (${value(m.color_interpretation)})`],
    ["Datatype", value(m.dtypes)],
    ["NoData", value(m.nodata)],
    ["CRS", data.crs],
    ["Oppløsning", formatResolution(data.resolution_x, data.resolution_unit)],
    ["Utbredelse (V, S, Ø, N)", bbox ?? "–"],
    ["Opptak", formatDate(data.acquisition_date)],
    ["Kilde for opptaksdato", value(m.acquisition_date_source)],
    ["Lastet opp", formatDate(data.uploaded_at)],
    ["Komprimering (original)", value(m.compression)],
  ];

  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
      {rows.map(([label, text]) => (
        <div key={label} className="contents">
          <dt className="text-slate-500">{label}</dt>
          <dd className="break-words">{text}</dd>
        </div>
      ))}
    </dl>
  );
}
