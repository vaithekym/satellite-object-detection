import { useQuery } from "@tanstack/react-query";
import ImageCard from "../components/imagery/ImageCard";
import UploadForm from "../components/imagery/UploadForm";
import { apiErrorMessage, listImages } from "../services/images";

export default function ImagesPage() {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["images"],
    queryFn: () => listImages(),
  });

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Bilder</h1>
      <UploadForm />

      <h2 className="mb-2 text-lg font-medium">Bildebibliotek{data ? ` (${data.total})` : ""}</h2>
      {isPending && <p role="status">Henter bilder …</p>}
      {isError && (
        <p role="alert" className="text-red-700 dark:text-red-400">
          Kunne ikke hente bilder: {apiErrorMessage(error)}
        </p>
      )}
      {data && data.items.length === 0 && (
        <p className="text-slate-500">Ingen bilder ennå. Last opp en GeoTIFF for å komme i gang.</p>
      )}
      {data && data.items.length > 0 && (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {data.items.map((image) => (
            <ImageCard key={image.id} image={image} />
          ))}
        </ul>
      )}
    </section>
  );
}
