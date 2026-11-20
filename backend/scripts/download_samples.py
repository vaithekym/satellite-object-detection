"""Download small, real, public sample rasters into data/samples/ (git-ignored).

Run from backend/:  python -m scripts.download_samples   (or `make samples`)

Samples:
- rgb_byte_landsat.tif: Landsat 7 RGB scene downsampled to ~300 m, from the rasterio test
  suite (EPSG:32618). Small and real; useful for upload/metadata tests, not for detection.
- naip_san_2022.tif / naip_san_2024.tif: 0.6 m USDA NAIP aerial imagery (public domain) over
  San Diego International Airport, read as a window from the full NAIP COG via Microsoft
  Planetary Computer. Same window for both years, usable later for change detection.
- naip_lax_2024.tif, naip_sfo_2024.tif, naip_pinal_2025.tif: NAIP windows over Los Angeles
  International, San Francisco International and Pinal Airpark (an aircraft storage site in
  Arizona), for testing aircraft detection in different settings.

Only some files:  python -m scripts.download_samples naip_lax_2024.tif naip_sfo_2024.tif
"""

import hashlib
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import rasterio
from pyproj import Transformer
from rasterio.enums import ColorInterp
from rasterio.windows import Window

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"

RGB_BYTE_URL = "https://raw.githubusercontent.com/rasterio/rasterio/1.4.3/tests/data/RGB.byte.tif"
RGB_BYTE_SHA256 = "d7cbe932c7ed74a627706a9e9df99f706df3e5abc7d45a49e9d00677a6b09eb4"

STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS_SIGN = "https://planetarycomputer.microsoft.com/api/sas/v1/sign?href="
# filename → (NAIP STAC item id, window centre (lon, lat)). Pinned item ids: reproducible.
NAIP_ITEMS: dict[str, tuple[str, tuple[float, float]]] = {
    "naip_san_2022.tif": ("ca_m_3211723_nw_11_060_20220425", (-117.1935, 32.7345)),
    "naip_san_2024.tif": ("ca_m_3211723_nw_11_060_20240506", (-117.1935, 32.7345)),
    "naip_lax_2024.tif": ("ca_m_3311805_ne_11_060_20240506", (-118.4081, 33.9425)),
    "naip_sfo_2024.tif": ("ca_m_3712229_ne_10_060_20240520", (-122.3890, 37.6160)),
    "naip_pinal_2025.tif": ("az_m_3211130_SW_12_060_20250727", (-111.3270, 32.5080)),
}
# Window size in pixels (0.6 m → ~1.2 km).
SIZE = 2048


def fetch_json(url: str, body: dict[str, Any] | None = None) -> Any:
    if not url.startswith("https://"):
        raise ValueError(f"Refusing non-https URL: {url}")
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers=headers)  # noqa: S310 (https only)
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return json.load(response)


def download_rgb_byte() -> None:
    target = SAMPLES_DIR / "rgb_byte_landsat.tif"
    with urllib.request.urlopen(RGB_BYTE_URL, timeout=60) as response:
        content = response.read()
    digest = hashlib.sha256(content).hexdigest()
    if digest != RGB_BYTE_SHA256:
        raise RuntimeError(f"Checksum mismatch for {RGB_BYTE_URL}: {digest}")
    target.write_bytes(content)
    print(f"wrote {target} ({len(content)} bytes)")


def download_naip(filename: str, item_id: str, center: tuple[float, float]) -> None:
    item = fetch_json(f"{STAC_SEARCH}", {"collections": ["naip"], "ids": [item_id]})
    feature = item["features"][0]
    href = feature["assets"]["image"]["href"]
    signed = fetch_json(SAS_SIGN + urllib.parse.quote(href, safe=""))["href"]

    target = SAMPLES_DIR / filename
    with rasterio.open(f"/vsicurl/{signed}") as src:
        to_src = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        x, y = to_src.transform(*center)
        row, col = src.index(x, y)
        col_off = min(max(col - SIZE // 2, 0), src.width - SIZE)
        row_off = min(max(row - SIZE // 2, 0), src.height - SIZE)
        window = Window(col_off, row_off, SIZE, SIZE)
        data = src.read(window=window)
        profile = src.profile | {
            "driver": "GTiff",
            "width": SIZE,
            "height": SIZE,
            "transform": src.window_transform(window),
            "compress": "deflate",
            "tiled": True,
            "blockxsize": 512,
            "blockysize": 512,
        }
        profile.pop("photometric", None)
        # The 4th band is near-infrared, not alpha: write it as an unspecified extra sample.
        profile["photometric"] = "RGB"
        profile["alpha"] = "UNSPECIFIED"
        with rasterio.open(target, "w", **profile) as dst:
            dst.write(data)
            dst.colorinterp = [ColorInterp.red, ColorInterp.green, ColorInterp.blue][
                : src.count
            ] + [ColorInterp.undefined] * max(src.count - 3, 0)
            dst.update_tags(
                ACQUISITIONDATETIME=feature["properties"]["datetime"],
                SOURCE="USDA NAIP via Microsoft Planetary Computer",
                SOURCE_ITEM=item_id,
            )
            dst.descriptions = ("red", "green", "blue", "nir")[: src.count]
    print(f"wrote {target} ({target.stat().st_size} bytes)")


def main(only: list[str]) -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    unknown = set(only) - set(NAIP_ITEMS) - {"rgb_byte_landsat.tif"}
    if unknown:
        raise SystemExit(f"Unknown sample(s): {', '.join(sorted(unknown))}")
    if not only or "rgb_byte_landsat.tif" in only:
        download_rgb_byte()
    for filename, (item_id, center) in NAIP_ITEMS.items():
        if not only or filename in only:
            download_naip(filename, item_id, center)


if __name__ == "__main__":
    main(sys.argv[1:])
