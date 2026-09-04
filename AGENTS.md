# AGENTS.md

## Current state

Python app for **GS1 DataMatrix verification** (ISO/IEC 15415-style grading,
decode via zxing-cpp). It IS a git repo: single initial commit on `master`,
remote `origin` = `https://github.com/lopatin2012/VerificatorDataMatrix.git`.

`samples/`, `models/`, `training/`, `test_image_codes/` are gitignored and
absent in this checkout — older "14/24 sample images" stats, `--dir samples`,
and `--dir test_image_codes` refer to machine-local datasets not present here.

## Versioning

`VERSION` lives in `version.py` (currently `1.0.17`), shown in the window title,
CLI (`--version`) and PDF footer. Rules:

- **Patch** (`1.0.x`): bump after every change to this `AGENTS.md` file.
- **Minor** (`1.x.0`): bump when a single session has more than 30 user
  requests.
- **Major** (`2.0.0`): bump when a single session has more than 300 user
  requests.

When in doubt, follow semver order: patch < minor < major.

## Environment

- Use the repo venv: `.venv\Scripts\python.exe` (Python 3.13.7). Bare `python`
  on PATH also resolves to it inside this repo. Core deps (numpy, opencv,
  zxing-cpp, reportlab, flask, waitress, Pillow) are installed there.
- `torch`/`torchvision` are NOT installed, so the NN locator is skipped
  silently — the core app must never require them.
- No test suite exists. Verify changes with `main.py --file` on a real image.
- Use `-X utf8` when piping Cyrillic output to files (console may mojibake).

## Commands

```
# GUI
& .venv\Scripts\python.exe main.py --gui
# analyze one image / a directory
& .venv\Scripts\python.exe main.py --file samples/G4_1.jpg
& .venv\Scripts\python.exe main.py --dir samples
# web service (Flask + waitress)
& .venv\Scripts\python.exe main.py --web --host 0.0.0.0 --port 8000
```

`--um-per-px` sets the microns-per-pixel calibration (default 10.0).

## Architecture

- `verifier.analyze_all(img)` is the entry point: decode + grid + grades + GS1
  for **every** DataMatrix found in the frame (returns a list of `Result`).
  `analyze(img)` returns the first one (or an error Result). Both the GUI and
  web render all results and let the user switch between codes.
- `ui.py` — Tkinter dashboard (scene with zoom/rotate/channel + heatmap,
  gauge, defect cards, GS1 chips, PDF, history strip).
- `webapp.py` + `webui/` — Flask/waitress web service (upload, camera,
  heatmap drawn client-side, PDF download). REST: `/api/analyze` (returns
  `{image, results:[...]}` — one entry per code, each with its own
  `result_id`), `/api/pdf`, `/api/version`. Results live in an in-memory LRU
  (50 entries), so `/api/pdf` 404s once a `result_id` ages out. Start via
  `main.py --web`.
- `report.py` — official PDF report (build_pdf), used by BOTH the web service
  and the GUI "Сформировать PDF отчёт" button (ui.py imports it too).
- `visual.py` — annotated-image builder (heatmap overlay), shared by UI/web.
- `verifier.problem_regions(res)` maps failed parameters to image-space
  polygons used by the heatmap.
- `core/decode.py` — `decode_all(img)` returns a DecodeResult per code found
  (deduped by position). zxing-cpp decode (color image; use
  `cvtColor(BGR2GRAY)`,
  NOT `cv2.imread(..., IMREAD_GRAYSCALE)` which yields different pixel values
  on this system and breaks zxing). Direct pass tries raw color, then
  thresholded binarizations (some low-contrast codes only decode there).
  Fallback: rebuild module grid + `is_pure`. Undecoded but located symbols are
  kept (for grading) only if their L+timing pattern score is strong — the
  run-based locator can emit whole-frame false positives on dark backgrounds.
- `core/detect.py` — L-pattern locator (zxing positions, plus a run-based
  locator for images zxing misses) and grid extraction via perspective warp.
  Handles inverted codes (white-on-dark) by trying both polarities.
- `core/nn_locator.py` — optional neural-net locator (ResNet18 corner
  regression, trained on `shortery/dm-codes`). Lazy `from . import nn_locator`
  in `decode.py`; if torch is missing the ImportError is caught and the
  locator is skipped silently. Last-resort fallback: NN crop → classic decode.
  Model weights in `models/dm_corners.pth` (gitignored). Training code in
  `training/` (gitignored; GPU; ML deps in `requirements-ml.txt`, NOT required).
- Sample codes are all **20x20 or 22x22**, but `_candidate_sizes` now tries
  the auto-detected module count (and nearby even sizes) first, then 20x20/
  22x22 — verified by decoding the reconstructed grid (is_pure trusts the
  grid, so decode success confirms the module count).
- `core/grade.py` — parameter grades 0–4; thresholds are lenient to match the
  reference output ("48% contrast → grade 4"). Parameter names follow the
  Axicon reference (Размерность печати, Левая/Нижняя часть шаблона "L",
  Последовательность тактовых модулей, Запас коррекции ошибок, ...).
- `gs1.py` — parses AIs from raw bytes (`\x1d` = GS separator) or HRI text.

## Gotchas

- Don't pin new libraries without checking Python 3.13 wheels (reportlab is
  already installed for the PDF report).
- `cv2.imread` fails on paths with Cyrillic characters (Windows path encoding);
  the web service works fine because it decodes upload bytes via `imdecode`.
- `G4_2.jpg` (white code on dark-blue background, perspective) is a known
  failure — the locator can't isolate it yet. Same class: codes photographed
  on dark backgrounds / with perspective (e.g. top-left patterns in
  `test_image_codes/*`) are not located — the run-based L-locator produces
  whole-frame or sub-pixel sliver false positives there, which `decode_all`
  filters by min-side/aspect/pattern-score.
- Grading is approximate, not calibrated to the Axicon reference tool.