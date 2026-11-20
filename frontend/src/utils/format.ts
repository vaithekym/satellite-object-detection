export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

const unitSymbols: Record<string, string> = { metre: "m", degree: "°" };

/** Pixel size in the source CRS's own unit, as reported by the API. */
export function formatResolution(x: number, unit: string | null): string {
  const value = Number(x.toPrecision(4));
  if (!unit) return String(value);
  const symbol = unitSymbols[unit];
  return symbol === "°" ? `${value}°` : `${value} ${symbol ?? unit}`;
}

export function formatLngLat(lng: number, lat: number): string {
  const ns = lat >= 0 ? "N" : "S";
  const ew = lng >= 0 ? "Ø" : "V";
  return `${Math.abs(lat).toFixed(5)}° ${ns}, ${Math.abs(lng).toFixed(5)}° ${ew}`;
}

export function formatDate(iso: string | null): string {
  if (!iso) return "Ukjent";
  return new Date(iso).toLocaleString("nb-NO", { dateStyle: "medium", timeStyle: "short" });
}
