import { previewUrl, type ImageSummary } from "../../services/images";
import { formatBytes, formatDate, formatResolution } from "../../utils/format";

export default function ImageCard({ image }: { image: ImageSummary }) {
  return (
    <li className="overflow-hidden rounded border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <img
        src={previewUrl(image.id)}
        alt={`Forhåndsvisning av ${image.filename}`}
        loading="lazy"
        className="aspect-square w-full bg-slate-100 object-contain dark:bg-slate-800"
      />
      <div className="p-3 text-sm">
        <div className="mb-1 truncate font-medium" title={image.filename}>
          {image.filename}
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-slate-600 dark:text-slate-400">
          <dt>Størrelse</dt>
          <dd>
            {image.width} × {image.height} px, {image.band_count} bånd
          </dd>
          <dt>Oppløsning</dt>
          <dd>{formatResolution(image.resolution_x, image.resolution_unit)}</dd>
          <dt>CRS</dt>
          <dd>{image.crs}</dd>
          <dt>Opptak</dt>
          <dd>{formatDate(image.acquisition_date)}</dd>
          <dt>Fil</dt>
          <dd>{formatBytes(image.file_size)}</dd>
          <dt>Status</dt>
          <dd>{image.processing_status}</dd>
        </dl>
      </div>
    </li>
  );
}
