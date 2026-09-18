# AGENTS.md

## Current state

Python app for **GS1 DataMatrix verification** (ISO/IEC 15415-style grading,
decode via zxing-cpp). Git repo on `master`; remote `origin` =
`https://github.com/lopatin2012/VerificatorDataMatrix.git`. History so far:
initial app → favicon + decode-speedup + block-display fix → GS-separator
copy + UI polish → Docker → dotted / white-on-dark decode. The working tree
often also carries uncommitted edits — run `git status` before assuming it is
clean.

Machine-local data, absent from git:
- `samples/`, `training/`, `models/` — gitignored and not in this checkout;
  older "14/24 sample images" stats and `--dir samples` refer to them.
- `test_image_codes/` — real product-pack photos, present in this checkout but
  UNTRACKED (not listed in `.gitignore`, so a bare `git add .` would stage
  them; only `.dockerignore` excludes them). Handy for `--dir test_image_codes`
  manual runs.

Dotted and inverted (white-on-dark) symbols decode through a dedicated
fallback (see `_dotted_results`); grading for them is coarse.

## Versioning

`VERSION` lives in `version.py` (currently `1.0.21`), shown in the window title,
CLI (`--version`) and PDF footer. Rules:

- **Patch** (`1.0.x`): bump after every change to this `AGENTS.md` file.
- **Minor** (`1.x.0`): bump when a single session has more than 30 user
  requests.
- **Major** (`2.0.0`): bump when a single session has more than 300 user
  requests.

When in doubt, follow semver order: patch < minor < major.

## Environment

- Core app runs in the repo venv: `.venv\Scripts\python.exe` (Python 3.11.9,
  core deps installed). It has **no torch**, so the NN locator is skipped there.
- `torch 2.11+cu128` is installed only for the system Python 3.13
  (`C:\Users\admin\AppData\Local\Programs\Python\Python313\python.exe`, or
  `py -3.13`). Use that interpreter to exercise the NN locator.
- Bare `python` on PATH is Python 3.14 **without pip** — do not use it.
- Tests: `main.py --selftest` (self-contained smoke tests — GS1 validation and
  synthetic solid/dotted/inverted decode). CI runs the same command
  (`.github/workflows/ci.yml`). Still verify decode changes on real images.
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
# built-in smoke tests (no sample files needed)
& .venv\Scripts\python.exe main.py --selftest
# Docker (repo-root Dockerfile runs the web service on :8501)
docker build -t dm-verifier .
docker run --rm -p 8501:8501 dm-verifier
```

`--um-per-px` sets the microns-per-pixel calibration (default 10.0).

## Repo / git

- Git repo, branch `master`, remote
  `https://github.com/lopatin2012/VerificatorDataMatrix.git`.
- `samples/`, `models/`, `training/` are **`.gitignore`d** — a fresh clone has
  none of them. The `samples` commands above and the NN fallback only work on
  this machine's working copy.

## Architecture

- `verifier.analyze_all(img)` is the entry point: decode + grid + grades + GS1
  for **every** DataMatrix found in the frame (returns a list of `Result`).
  `analyze(img)` returns the first one (or an error Result). Both the GUI and
  web render all results and let the user switch between codes.
- `ui.py` — Tkinter dashboard (scene with zoom/rotate/channel + heatmap,
  gauge, defect cards, GS1 chips, PDF, history strip).
- `webapp.py` + `webui/` — Flask/waitress web service (upload, camera,
  heatmap drawn client-side, PDF download, history strip with CSV/PDF export).
  REST: `/api/analyze` (returns `{image, results:[...]}` — one entry per code,
  each with its own `result_id`), `/api/history`, `/api/history/clear` (POST),
  `/api/result/<id>` (reload a past check), `/api/history.csv`,
  `/api/history.pdf`, `/api/pdf`, `/api/version`. Each stored entry keeps
  `{res, img, payload, thumb, ts}`. Results live in an in-memory LRU (50
  entries), so a `result_id` (and its history entry) 404s once it ages out;
  history is lost on restart. Generated PDFs go to a temp dir
  (`PDF_DIR`), never under `webui/` (which is served statically). Responses
  get `Cache-Control: no-store` (added via `@app.after_request`) so browsers
  pick up edited JS/CSS immediately. Start via `main.py --web`.
- `report.py` — official PDF report (`build_pdf`), used by BOTH the web service
  and the GUI "Сформировать PDF отчёт" button (ui.py imports it too); also
  `build_history_pdf(entries, path)` for the history export. `visual.py` was
  removed — UI and web draw their own overlays.
- `verifier.problem_regions(res)` maps failed parameters to image-space
  polygons used by the heatmap.
- `core/decode.py` — `decode_all(img)` returns a DecodeResult per code found
  (deduped by position). zxing-cpp decode (color image; use
  `cvtColor(BGR2GRAY)`,
  NOT `cv2.imread(..., IMREAD_GRAYSCALE)` which yields different pixel values
  on this system and breaks zxing). Direct pass tries raw color, then
  thresholded binarizations (some low-contrast codes only decode there).
  Fallback: rebuild module grid + `is_pure`. Undecoded but located symbols are
  kept (for grading) only if their L+timing pattern score is strong, their grid
  is >= 8 modules per side and the quad passes the min-side/aspect checks — the
  run-based locator can emit whole-frame / tiny (4x4) false positives.
- Dotted / white-on-dark codes: `_dotted_results` (runs only when nothing
  decoded) closes the dot mask with a small elliptical kernel, lets zxing find
  the symbol, then rebuilds the grid from the zxing quad by warping
  `255 - closed` to a square and resampling N×N (`_DOT_MODULE_SIZES`, 10..32).
  Grid decode must match the zxing text exactly. Symbol reflectance is inverted
  so `grade.py`'s "dark module = low reflectance" assumption holds.
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
- `gs1.py` — parses AIs from raw bytes (`\x1d` = GS separator, skipped between
  fields) or HRI text. `gs1.validate(elements)` returns warnings (unknown AI,
  fixed-length mismatch, GTIN/SSCC mod-10 check digit), surfaced as
  `Result.gs1_warnings` and `to_dict()["gs1_warnings"]`.
- Content copy preserves the GS separator `\x1d` (only FS `\x1c`/RS `\x1e` are
  stripped): `verifier.plain_content()` → `content_raw`; the web REST
  `content_plain` field carries the same raw form; both the GUI and web copy
  buttons put the raw `\x1d` on the clipboard and only the on-screen preview
  substitutes a visible `[GS]` marker. `\x1d` is the standard GS1 field
  separator needed to re-parse variable-length AIs, so don't strip it in copy
  paths.

## Gotchas

- Don't pin new libraries without checking Python 3.13 wheels (reportlab is
  already installed for the PDF report).
- The web server holds code in memory — waitress has NO auto-reload. After
  editing `.py`/`webui/`, the running process keeps serving the OLD code until
  restarted. A leftover server started earlier (even by another agent/session)
  can sit unnoticed on port 8000 and report a stale `/api/version`; check
  `Get-NetTCPConnection -LocalPort 8000` before debugging "changes don't
  apply".
- `cv2.imread` fails on paths with Cyrillic characters (Windows path encoding);
  the web service works fine because it decodes upload bytes via `imdecode`.
- Dotted / white-on-dark codes decode only through `_dotted_results`, which is
  slower (~1 s/code) and runs after the normal pipeline fails. Grading for them
  is coarse (reflectance is inverted). Codes photographed on dark backgrounds
  or with strong perspective (e.g. product packs) may still fail — the
  run-based L-locator can produce whole-frame / sub-pixel sliver false
  positives, which `decode_all` filters by min-side/aspect/pattern-score.
- Grading is approximate, not calibrated to the Axicon reference tool.
