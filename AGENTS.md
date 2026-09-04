# AGENTS.md

## Current state

Working Python app for **GS1 DataMatrix verification** (ISO/IEC 15415-style
grading). Built and tested on this machine against the 24 sample images in
`samples/` (grades G0–G4, ERROR). Not a git repo. 14/24 images decode;
the rest are genuinely bad codes (G0–G2, ERROR) or the known `G4_2` case.

## Versioning

`VERSION` lives in `version.py` and is shown in the window title, CLI
(`--version`) and PDF footer. Rules:

- **Patch** (`1.0.x`): bump after every change to this `AGENTS.md` file.
- **Minor** (`1.x.0`): bump when a single session has more than 30 user
  requests.
- **Major** (`2.0.0`): bump when a single session has more than 300 user
  requests.

When in doubt, follow semver order: patch < minor < major.

## Runtime quirk (important)

- The `python` on PATH is Python 3.14 **without pip**. The working interpreter
  is Python 3.13 at `C:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe`.
  Always invoke it explicitly, never bare `python`.
- Dependencies are installed ONLY for Python 3.13 (`pip` on PATH targets 3.13).

## Commands

```
# GUI
& "C:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe" main.py --gui
# analyze one image / a directory
& "C:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe" main.py --file samples/G4_1.jpg
& "C:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe" main.py --dir samples
```

Use `-X utf8` when piping Cyrillic output to files (console may mojibake).

## Architecture

- `verifier.analyze(img)` is the entry point: decode + grid + grades + GS1.
- `ui.py` — Tkinter dashboard (scene with zoom/rotate/channel + heatmap,
  gauge, defect cards, GS1 chips, PDF via reportlab, history strip).
- `webapp.py` + `webui/` — Flask/waitress web service (upload, camera,
  heatmap drawn client-side, PDF download). Start via `main.py --web`.
- `visual.py` — annotated-image builder (heatmap overlay), shared by UI/web.
- `verifier.problem_regions(res)` maps failed parameters to image-space
  polygons used by the heatmap.
- `core/decode.py` — zxing-cpp decode (color image; use `cvtColor(BGR2GRAY)`,
  NOT `cv2.imread(..., IMREAD_GRAYSCALE)` which yields different pixel values
  on this system and breaks zxing). Direct pass tries raw color, then
  thresholded binarizations (some low-contrast codes only decode there).
  Fallback: rebuild module grid + `is_pure`.
- `core/detect.py` — L-pattern locator (zxing positions, plus a run-based
  locator for images zxing misses) and grid extraction via perspective warp.
  Handles inverted codes (white-on-dark) by trying both polarities.
- `core/nn_locator.py` — optional neural-net locator (ResNet18 corner
  regression, trained on `shortery/dm-codes`). Lazy torch import; last-resort
  fallback in `decode.py` (crop + classic pipeline). Model weights in
  `models/dm_corners.pth`. Training code in `training/` (uses GPU; the ML deps
  are in `requirements-ml.txt`, NOT required for the core app).
- Sample codes are all **20x20 or 22x22** — `_candidate_sizes` only tries
  these, verified by decoding the reconstructed grid (is_pure trusts the grid,
  so decode success confirms the module count).
- `core/grade.py` — parameter grades 0–4; thresholds are lenient to match the
  reference output ("48% contrast → grade 4"). Parameter names follow the
  Axicon reference (Размерность печати, Левая/Нижняя часть шаблона "L",
  Последовательность тактовых модулей, Запас коррекции ошибок, ...).
- `gs1.py` — parses AIs from raw bytes (`\x1d` = GS separator) or HRI text.

## Gotchas

- Don't pin new libraries without checking Python 3.13 wheels (reportlab is
  already installed for the PDF report).
- `G4_2.jpg` (white code on dark-blue background, perspective) is a known
  failure — the locator can't isolate it yet.
- Grading is approximate, not calibrated to the Axicon reference tool.