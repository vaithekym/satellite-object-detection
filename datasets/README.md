# Datasets

No imagery or labels are committed. Everything is downloaded into `data/` (git-ignored) by
reproducible scripts that pin exact source items.

## Sample imagery (`make samples`)

`backend/scripts/download_samples.py` reads small windows directly from full-size Cloud Optimized
GeoTIFFs. Nothing large is downloaded.

| File | Source | Area | Resolution | CRS | Size |
|---|---|---|---|---|---|
| `rgb_byte_landsat.tif` | Landsat 7 scene from the [rasterio test suite](https://github.com/rasterio/rasterio) (tag 1.4.3), SHA-256 checked | Bahamas | about 300 m (downsampled) | EPSG:32618 | 791 × 718 |
| `naip_san_2022.tif`, `naip_san_2024.tif` | USDA NAIP via Microsoft Planetary Computer | San Diego Intl. Airport (same window both years) | 0.6 m, RGB + NIR | EPSG:26911 | 2048 × 2048 |
| `naip_lax_2024.tif` | NAIP | Los Angeles Intl. Airport | 0.6 m | EPSG:26911 | 2048 × 2048 |
| `naip_sfo_2024.tif` | NAIP | San Francisco Intl. Airport | 0.6 m | EPSG:26910 | 2048 × 2048 |
| `naip_pinal_2025.tif` | NAIP | Pinal Airpark, Arizona (aircraft storage) | 0.6 m | EPSG:26912 | 2048 × 2048 |

The NAIP windows are about 1.2 × 1.2 km around a fixed centre, read from a pinned STAC item id and
written as tiled, DEFLATE-compressed GeoTIFFs. The NIR band is marked as an undefined extra band, not
as alpha. Each file carries `ACQUISITIONDATETIME` (the STAC item's datetime, where NAIP records the
acquisition date with a nominal time of day), `SOURCE` and `SOURCE_ITEM` tags.

The San Diego pair (2022/2024, with major construction at Terminal 1) is intended for change
detection.

Licences: NAIP is public domain (USDA Farm Service Agency). The Landsat sample comes from the
rasterio repository (BSD-licensed code; Landsat data is public domain).

## Labelled evaluation data (`make evaluate`)

`DOTA8` is downloaded by Ultralytics on first use into `data/datasets/dota8`: 8 images with 4 for
validation, a tiny sample of DOTA v1 meant for smoke tests. **DOTA is licensed for academic use
only**, and its images overlap the pretrained model's training data, so scores on it are not an
accuracy estimate. See [docs/ml-pipeline.md](../docs/ml-pipeline.md).

## Larger public datasets (not downloaded automatically)

| Dataset | Good for | Access |
|---|---|---|
| [DOTA](https://captain-whu.github.io/DOTA/) | Oriented object detection in aerial imagery; what the current model is trained on | Registration; academic use only |
| [xView](https://xviewdataset.org/) | Small objects in 0.3 m satellite imagery, 60 classes | Registration; check terms |
| [SpaceNet](https://spacenet.ai/datasets/) | Buildings and roads | AWS Open Data (`s3://spacenet-dataset`, no sign-in required); CC BY-SA 4.0 |
| Sentinel-2 (e.g. via Planetary Computer) | Land cover and large-scale change detection, 10–60 m | Free; not suitable for individual vehicles or aircraft |

To evaluate on real target imagery, label a small held-out set (e.g. NAIP airport tiles) with
oriented boxes and pass (predictions, ground truth) pairs to `app.ml.metrics.evaluate()`. Start
with a small, reproducible subset, and do not download full datasets by default.
