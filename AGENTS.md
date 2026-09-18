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

## Known gaps / TODO

- **Grade determination still needs work — this is the main remaining item.**
  `core/grade.py` thresholds are approximate and do NOT reproduce the Axicon
  reference. The `G0..G4` labels in the local sample filenames are the owner's
  reference grades, not ours, and our overall class often differs. Calibration
  needs a labeled set of real codes with reference grades (per parameter and
  overall); the owner is collecting them. Until then, do not claim grade
  accuracy.
- **Read/no-read threshold for very poor codes.** Some codes the reference
  treats as errors are still decoded here as class 0 (e.g. local sample
  `samples/G_ERROR_9`, ex-`G0_1`). No rule marks such reads as errors yet.
- **Local unreadable samples** (not in git): `G0_5`, `G1_1`, `G1_2`,
  `G_ERROR_1`, `G_ERROR_3`, `G_ERROR_10` are not decoded by any path (only
  `G_ERROR_3` reaches zxing, with a ChecksumError).
- Dotted / white-on-dark grading is coarser than solid codes (see Gotchas).
- Optional / unscheduled: persist web history (currently in-memory LRU);
  add an upload-size limit and/or auth when `--web` is exposed beyond localhost.

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
- `LICENSE` — MIT, Copyright (c) 2026 Maxim Lopatin (attribution required);
  keep it and the README license section on redistribution.
- `samples/`, `models/`, `training/`, `docs/` are **`.gitignore`d** — a fresh
  clone has none of them. The `samples` commands above and the NN fallback only
  work on this machine's working copy; `docs/` (CRPT PDFs) must never be
  committed.

## Build / release

- `build.spec` + `build.ps1` build a single-file Windows exe for end users
  (`dist/DataMatrixVerifier.exe`) with PyInstaller, so they need no Python or
  deps. It bundles `webui/` + `favicon.ico` and **excludes torch** (the NN
  locator is skipped at runtime); `build/` and `dist/` are gitignored.
- PyInstaller lives in the repo venv (not in `requirements.txt`):
  `.venv\Scripts\python.exe -m pip install pyinstaller`, then `.\build.ps1`.
- Releases are published on GitHub with `gh release create v<version>`
  attaching the built exe; the tag matches `version.py`.

## Architecture

- `verifier.analyze_all(img)` is the entry point: decode + grid + grades + GS1
  for **every** DataMatrix found in the frame (returns a list of `Result`).
  `analyze(img)` returns the first one (or an error Result). Both the GUI and
  web render all results and let the user switch between codes.
- `ui.py` — Tkinter dashboard (scene with zoom/rotate/channel + heatmap,
  gauge, defect cards, GS1 chips, PDF, history strip). Draws a "Код не найден"
  banner on the scene when the current result has no symbol.
- `webapp.py` + `webui/` — Flask/waitress web service (upload, camera,
  heatmap drawn client-side, PDF download, history strip with CSV/PDF export).
  When nothing is found `/api/analyze` still returns the `image` (plus
  `error`), the client canvas draws a "Код не найден" banner on it, and the
  gauge/params/defects/data panels are reset (no stale values from the
  previous check).
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
  A successful direct decode also supplies the exact module count: `_barcode_size`
  reads it from `Barcode.to_image(scale=1)` (1 px/module; bbox of dark modules),
  and `_symbol_for_quad(size_hint=...)` resamples at that count (trying small
  quad scalings) so geometry is right. A wrong count can still decode (e.g. a
  `20x4` grid for a 22x22 symbol), so the hint wins, and if the grid cannot
  itself decode there (glare) the hinted geometry is still used.
- Dotted / white-on-dark codes: `_dotted_results` (runs only when nothing
  decoded) closes the dot mask with a small elliptical kernel, lets zxing find
  the symbol, then rebuilds the grid from the zxing quad by warping
  `255 - closed` to a square and resampling N×N (`_DOT_MODULE_SIZES`, 10..32).
  N is chosen from the symbol's own dot pitch (`_dot_pitch`, FFT of the warped
  mask, both axes must agree) rather than the first size whose grid pure-decodes
  — a wrong count can still decode (e.g. 32 for a 20x20 dot code). A symbol with
  no consistent pitch (e.g. a photo of a screen with moiré) is rejected as a
  false positive. If the full-frame pass detects no symbol at all, the code is
  likely small, so `_dotted_tiles` retries on overlapping 2x2 crops with a
  local (crop) Otsu threshold — the global threshold loses these. Tile hits use
  a relaxed rebuild (`_symbol_from_dotted_tile`) that trusts zxing's text and
  picks the best-fitting module count. Tiles run only when the full-frame pass
  detected nothing, so screen/moire photos (which it does detect, then rejects)
  are not re-admitted. Symbol reflectance is inverted so `grade.py`'s
  "dark module = low reflectance" assumption holds.
- `core/detect.py` — L-pattern locator (zxing positions, plus a run-based
  locator for images zxing misses) and grid extraction via perspective warp.
  Handles inverted codes (white-on-dark) by trying both polarities.
- `core/nn_locator.py` — optional neural-net locator (ResNet18 corner
  regression, trained on `shortery/dm-codes`). Lazy `from . import nn_locator`
  in `decode.py`; if torch is missing the ImportError is caught and the
  locator is skipped silently. Last-resort fallback: NN crop → classic decode.
  Model weights in `models/dm_corners.pth` (gitignored). Training code in
  `training/` (gitignored; GPU; ML deps in `requirements-ml.txt`, NOT required).
- Sample codes are mostly **20x20 or 22x22**, but `_candidate_sizes` tries the
  exact count reported by zxing (`_barcode_size`) first, then the auto-detected
  module count (and nearby even sizes), then 20x20/22x22. A wrong grid size can
  still decode, so the zxing size hint is authoritative; without one, decode
  success of the reconstructed grid is the confirmation.
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
- `cv2.imread` fails on paths with Cyrillic characters (Windows path encoding).
  The web service is fine (it decodes upload bytes via `imdecode`); the CLI and
  GUI use `verifier.imread_unicode` (`np.fromfile` + `cv2.imdecode`) instead.
- Dotted / white-on-dark codes decode only through `_dotted_results`, which is
  slower (~1 s/code, several s more when `_dotted_tiles` runs) and runs after
  the normal pipeline fails. Grading for them is coarse (reflectance is
  inverted). Codes photographed on dark backgrounds
  or with strong perspective (e.g. product packs) may still fail — the
  run-based L-locator can produce whole-frame / sub-pixel sliver false
  positives, which `decode_all` filters by min-side/aspect/pattern-score.
- Grading is approximate, not calibrated to the Axicon reference tool.

## Chestny Znak (ЧЗ) — offline only

The app is deliberately **fully offline**; it never calls ЧЗ. Decision made
after reading `docs/True_API_GIS_MT.pdf` and `docs/API_СУЗ_3.0.pdf` (gitignored,
not in git):

- There is **no token-free method** to get product info by DataMatrix code.
  Product/code lookups all require a Bearer token:
  `POST /api/v3/true-api/cises/info`, `POST /cises/short/list`, `/cises/list`,
  and by-GTIN `POST /api/v4/true-api/product/info` — examples all send
  `Authorization: Bearer <ТОКЕН>`. "Публичный" in the docs means "any
  authenticated participant", not anonymous.
- Genuinely `без токена` are only `GET /participants?inns=...` and
  `GET /api/v4/true-api/edo/inn/{inn}` — neither returns product info.
- The token comes from a УКЭП (`/auth/key` → `/auth/simpleSignIn`), i.e. a
  participant account is required.
- Stands: `https://markirovka.crpt.ru/api/v3/true-api` (and `/v4/true-api`);
  sandbox `https://markirovka.sandbox.crptech.ru/...`. `API_СУЗ` is
  СУЗ-ОБЛАКО (orders/emission), no consumer lookup either.

If a "Сведения в ЧЗ" feature is ever wanted, it must be token-based (network +
participant credentials), so it is opt-in and never on by default.
