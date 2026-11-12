# Past Storm

The archive is bundled as static files under `frontend/data/past/`. The existing
Pages workflow copies these files alongside the live monitor. The Cloudflare
schedule only runs the live monitor batch.

| Case | Hourly UTC window | Source |
| --- | --- | --- |
| Hurricane Isaias (AL09 2026) | 2026-10-08 00:00 to 2026-10-09 18:00 | NHC ATCF B-deck and NOAA GOES-19 ABI C14 |
| Hurricane Polo (EP17 2026) | 2026-09-21 06:00 to 2026-09-29 00:00 | NHC ATCF B-deck and NOAA GOES-18 ABI C14, with GOES-19 as a fallback |

The slider displays actual UTC scan times. The archive looks for a scan within
30 minutes of each requested hour and keeps the hour on the track if no scan
is available. Each image records its satellite and source URL.
Centers between official fixes are interpolated linearly in
latitude and longitude, using the shorter longitude difference across the date
line. The crop is centered at the scan time. The page's Infer button reveals the
saved prediction for that frame.

After replacing the checkpoint, run this from the project root using the
existing Python environment:

```powershell
$env:PYTHONPATH="$PWD/.runtime"
python -m backend.past_cases
```

`R34_MODEL_PATH` can select a different checkpoint. The manifest records the
checkpoint SHA-256. Successful frames are reused when the hash matches. A new
checkpoint recomputes their distributions using the saved Kelvin crops when
available. Crops are kept in the ignored `.cache/past-storms/` directory.
Commit the updated archive files in `frontend/data/past/` to publish them on
the next Pages deployment.
