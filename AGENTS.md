# AGENTS.md

Python app for **GS1 DataMatrix verification**: locate symbols in photos, decode
with zxing-cpp, grade print quality ISO/IEC 15415-style, show results in a
Flask web UI or the CLI. All user-facing text (web, CLI, PDF) is Russian. Branch `master`; remote `origin` =
`https://github.com/lopatin2012/VerificatorDataMatrix.git`.

The working tree often carries uncommitted edits — run `git status` before
assuming it is clean. `README.md` is the (Russian) user documentation; update it
when user-facing behavior changes.

## Commands

Always invoke the repo venv explicitly. Bare `python` is the system 3.14.5 with
none of the app's deps; the README now says so too.

```
# smoke tests — the ONLY test suite (no pytest/unittest); CI runs this
.venv\Scripts\python.exe main.py --selftest

# web service (default; Flask app served by waitress)
.venv\Scripts\python.exe main.py
.venv\Scripts\python.exe main.py --web --host 0.0.0.0 --port 8010

# one image / a directory of images (all codes; --json for automation)
.venv\Scripts\python.exe main.py --file samples/G4_1.jpg
.venv\Scripts\python.exe main.py --dir test_image_codes
.venv\Scripts\python.exe main.py --dir test_image_codes --json

# Docker image runs the web service on :8501 (not 8010)
docker build -t dm-verifier .
docker run --rm -p 8501:8501 dm-verifier

# standalone Windows exe
.venv\Scripts\python.exe -m pip install pyinstaller
.\build.ps1
```

`--um-per-px` sets the calibration (default 10.0 µm/px). There is no lint,
typecheck, formatter, or codegen config — don't invent one.

## Environment and local data

- Venv is Python 3.13.7 with core deps installed. No torch anywhere, so the NN
  locator is skipped; to exercise it install `requirements-ml.txt` (CUDA wheel
  index) first. Pin new libs only when Python 3.13 wheels exist.
- `samples/`, `training/`, `models/`, `docs/` are `.gitignore`d and absent from
  this checkout (the owner's calibration set grows under `samples/new_codes/`).
  `docs/` holds CRPT API PDFs and must never be committed.
- `test_image_codes/` (12 real product-pack photos, absent from this checkout)
  is `.gitignore`d, so `git add .` cannot stage customer packaging; it also
  stays out of the Docker image. Use it for manual decode checks.
- `webui/` is served statically: never write generated files there. The old
  `webui/_report.pdf` leftover was deleted; PDFs go to `PDF_DIR` (temp).
- Use `-X utf8` when piping Cyrillic output to files (console may mojibake).
- `LICENSE` is MIT, Copyright (c) 2026 Maxim Lopatin; keep it and the README
  license section.

## Testing

`main.py --selftest` (`selftest.py`) is self-contained: GS1 parsing/validation
(including GS-separated variable fields and dates) plus synthetic solid, dotted,
and inverted DataMatrix decode and geometry/grading regressions (45 checks). It
asserts that dimensions are reported in source microns, that a rectangular
ECC200 symbol (12x26) is not penalised for its aspect ratio, that the default
calibration is flagged, that report values use a decimal comma, that
read/GS1/quality statuses and threshold scales are exposed, and that GS1
detection, dates, expiry warnings and HRI are correct. Real images are not
in git, so still verify decode/geometry changes manually against
`test_image_codes/` or the owner's `samples/`. CI
(`.github/workflows/ci.yml`) runs the same command on Ubuntu after installing
`libgl1`/`libglib2.0-0`.

## Architecture

- `main.py` — argparse entry: web service (default when no `--file/--dir`),
  CLI, selftest. `--um-per-px` accepts a comma and defaults to `None`, which
  means 10 µm/px **marked as approximate** (never silently precise). The CLI
  prints **all** codes per image and exits 1 if any image decoded nothing;
  `--json` emits `[{file, results:[to_dict]}]` (or `{file, error}`) for
  automation; `--crpt` is CLI-only.
- `tools/` — Windows drag-and-drop launchers (not bundled into the exe):
  `quick_check.bat` → console `main.py --file` with `pause`, `quick_web.bat` →
  `tools/quick_web.py` (`--port 8010` default, picks the next free port, opens
  the browser when the socket accepts connections, `--host 0.0.0.0` for LAN).
  They resolve the repo root as `..` and use the repo `.venv`. Keep paths quoted
  so Cyrillic/space paths work. Never auto-kill an existing server: the
  free-port pick avoids serving stale code. `evaluate_grades.py` compares
  `G0..G4` / `G_ERROR` filename labels with our grade (confusion matrix,
  `--csv`, `--json`, `--strict`); no network, no app changes.
- `verifier.analyze_all(img)` is the pipeline entry: decode + grid + grades +
  GS1 for **every** symbol, returning a list of `Result` sorted best-first
  (decoded/higher grade first); `analyze(img)` returns the first or an error
  Result. `um_per_px=None` selects `DEFAULT_UM_PER_PX` and sets
  `Result.calibration_default=True`; `calibration_note()`/`calibration_warning()`
  feed every report. `overall_class` is human-readable (`4,0 · 22×22 · 160 мкм`),
  while `class_code` keeps the compact `4.0/22/160`. Statuses are separate:
  `validation`/`read_ok` (decode), `gs1_status` (`ok|warn|none`),
  `quality_ok`/`quality_status` (`good|bad|unknown`), while `good` is the
  combined verdict. `to_dict()` carries all of them plus `um_per_px`,
  `calibration_default/note/warning`, `module_px_x/y` and per-param
  `display`/`scale`; `content_hri`, per-element `ai`/`label`/`display_value`,
  and `symbology` are here too. `hri_content()`, `score_of`, `is_good`,
  `plain_content`, and `problem_regions` live here too. GS1 vs plain is decided
  by `gs1.is_gs1` + `DecodeResult.symbology_id` (`]d2`/`]d5`); plain codes get
  no elements/warnings.
- `core/decode.py` — `decode_all` returns one `DecodeResult` per symbol,
  deduped by quad. zxing gets an RGB image, and gray comes from
  `cvtColor(BGR2GRAY)` — **never** `cv2.imread(..., IMREAD_GRAYSCALE)`, which
  yields different pixels on this machine and breaks zxing. Tries raw color,
  then thresholded passes (96/128/160/192), then grid rebuild + `is_pure`.
  Undecoded but located symbols are kept for grading only if the quad is
  plausible (>= 8 modules/side, >= 24 px, aspect <= 5, <= 80% of frame) and the
  L+timing pattern score is strong — the run-based locator emits whole-frame
  and tiny (4x4) false positives. `DecodeResult.symbology_id` carries zxing's
  AIM identifier (`]d1`, `]d2`, ...) and `DecodeResult.uec` its unused-error-
  correction ratio (from `extra['UEC']`); the dotted path keeps both.
- The zxing decode supplies the authoritative module count: `_barcode_size`
  reads it from `Barcode.to_image(scale=1)` and passes it as `size_hint`
  through `_symbol_for_quad`; a wrong grid can still decode (e.g. 20x4 for a
  22x22 symbol), so the hint wins. Without a hint, `_candidate_sizes` tries the
  auto-detected count and nearby even sizes, then 20x20/22x22 (samples are
  mostly those).
- Dotted / white-on-dark fallback (`_dotted_results`, only when nothing
  decoded): morphological close, zxing locate, warp `255 - closed`, resample
  N×N where N comes from the symbol's dot pitch (`_dot_pitch` FFT, both axes
  must agree) rather than the first size that pure-decodes. Rejecting an
  inconsistent pitch keeps screen/moiré photos from becoming false positives.
  If full-frame detection found nothing at all, `_dotted_tiles` retries 2x2
  crops with local Otsu. Symbol reflectance is inverted so `grade.py`'s
  "dark module = low reflectance" assumption holds.
- `core/detect.py` — L-pattern locator (zxing positions + run-based fallback)
  and perspective-warp grid extraction; tries both polarities. `module_px` and
  `module_px_x/y` are in **source image pixels**, not in the 800-px warp frame
  (the warp is an arbitrary square and must not leak into microns/aperture).
  `measure_quiet_zone()` re-warps with a margin and runs once per final symbol
  from `verifier._analyze_one`; `Symbol.quiet_zone` is in modules. For dotted
  symbols it stays `None` and `grade.py` falls back to 1.0.
- `core/nn_locator.py` — optional ResNet18 corner regressor, lazy `torch`
  import; missing torch is silently ignored. Last-resort crop-then-decode.
- `core/grade.py` — parameter grades 0–4, overall = minimum. Thresholds are
  approximate (see Known gaps). Parameter names are exact Russian strings that
  `problem_regions` and the UI match; renaming one silently breaks the heatmap.
  Axial non-uniformity compares the physical **module pitch** along X/Y, never
  the row/column counts (that zeroed every rectangular ECC200 symbol). Values
  use a Russian decimal comma; print growth is signed (`+2,0 мкм; +2,0%`) and
  quiet zone is `2,8 мод.`. `SCALES` holds the **actual** 4/3/2/1 thresholds
  used by the code; `Param.scale` feeds the PDF/CLI/web reports (do not
  replace them with ISO numbers unless the grades themselves are recalibrated).
  `grade_symbol(..., uec=...)` uses zxing's UEC ratio when present and only
  falls back to `SC-20` for grid/dotted paths. Symbol contrast now uses the
  ISO-oriented bands `70/55/40/20`; illumination non-uniformity uses a robust
  MAD-based spread (`_relative_mad`) so one edge-affected light module cannot
  turn a clean code into a 12% failure. The remaining parameters are still
  approximate. Use `tools/evaluate_grades.py` before changing more thresholds.
  `verifier.is_good` treats a decoded code with `min_grade > 1.5` as good — that
  is the Chestny Znak print-quality threshold, so grade 2,0 passes: never
  describe 2,0 as a failure in the UI, help texts or tips. The Товар tab help
  spells this out (statuses in ГИС МТ, answer meanings, grade bands).
- `gs1.py` — parses AIs from raw bytes or HRI; a GS/FNC1 separator is
  authoritative for variable-length fields. Supports pattern AIs (310n–316n,
  390n–395n). `validate()` returns warnings (unknown AI, fixed-length mismatch,
  impossible dates, expired/near-expiry 15/16/17, GTIN/SSCC mod-10), surfaced
  as `Result.gs1_warnings`. `is_gs1()` is a documented heuristic: FNC1/GS or
  `]d2`/`]d5` or a valid GTIN/SSCC/ITIP at the start; a plain numeric DataMatrix
  starting with a valid GTIN is the ambiguous case. `Element.display_value()`
  renders `ДД.ММ.ГГГГ` (DD=00 -> last day), `display_label()` avoids
  "AI 17 [AI 17]", and `format_gs1_date()` is shared with the expiry check.
- `crpt.py` — opt-in Chestny Znak mobile API lookup (`lookup`/`parse_response`),
  no deps beyond `urllib`, 10 s timeout, normalized Russian statuses/warnings
  and dates. Used by the Web «Товар» tab, `/api/crpt` and CLI `--crpt`; see the
  dedicated section below for the no-auto-call policy.
- Copy paths preserve the GS separator `\x1d` (only FS `\x1c`/RS `\x1e` are
  stripped): `plain_content()` feeds `content_raw`/`content_plain`. The web UI
  copies the raw string and only renders `[GS]` on screen. Don't strip `\x1d` —
  it is required to re-parse variable-length AIs.
- `webapp.py` + `webui/` — Flask/waitress. **The server keeps no history or
  uploaded images** (so no auth is needed): REST is `/api/analyze` (returns
  `{image, results:[...]}`, one `result_id` per code; with no code it still
  returns `image` plus `error`), `/api/pdf` (multipart image + `um_per_px` +
  `result_index`/`code` + optional `crpt` JSON → re-runs `analyze_all` and
  builds the report), `/api/history.pdf` (POST `{items:[row,...]}` from the
  client, max 500 rows), `/api/crpt` (opt-in product lookup by `code`, 200
  with normalized data, 400/404/502 on error; normalized result cached in
  `CRPT_CACHE` only), `/api/version`. Removed on purpose: `/api/history*`,
  `/api/result/<id>`, `/api/reanalyze`.
  `/api/analyze` accepts an optional `um_per_px` form field (comma or dot,
  must be > 0; invalid values return 400) and stores calibration fields in the
  payload; the calibration input is persisted in `localStorage`. `analyze_all`
  runs under `ANALYZE_LOCK` (one at a time). The UI has a HRI copy button and
  chips built with `textContent` (never innerHTML for barcode data). Upload cap
  is 25 MB (`MAX_CONTENT_LENGTH`); a 413
  returns JSON. PDFs go to `PDF_DIR` (a temp dir), never `webui/`.
  `@app.after_request` sets `Cache-Control: no-store`. Default listen is
  `127.0.0.1:8010` (8000 is often taken by Apache on the owner's machine).
- `webui/` — responsive dashboard: dark scene matte with camera preview,
  health card with measurement rows, and tabs `Данные / Товар / Дефекты /
  Отчёт`; history strip with time. Keep JS IDs stable or update `app.js`
  selectors together. Camera is open-then-capture (first click previews,
  second captures); tabs are wired by `data-tab`. Scene navigation: drag to
  pan, wheel to zoom at the cursor, Reset view, and fullscreen on the `.scene`
  card (`state.panX/panY` drive both drawImage and the overlay mapping).
  `analyze` uses XHR for a real upload percentage, then an indeterminate bar;
  `PROCESS_TIPS` is a list of `{kind, label, text}` entries (`site`/`cz`/`fact`)
  rotated every 5 s with a colored badge — site capabilities, Честный Знак
  info and DataMatrix facts; the drop zone also shows four `dropfeats`
  capability chips. The Товар tab has a `<details>`
  help block. There is no server-side stage stream. History lives in the
  browser: IndexedDB `dm_verifier` / store `history`, up to 50 entries
  `{id, ts, thumb, payload, image (Blob), um, crpt, result_index, file_name}`;
  CSV/TXT are built in JS, history PDF posts those rows to `/api/history.pdf`.
  `state.lastFile`/`lastFileName` keep the current Blob so `/api/pdf` and
  re-analysis (including calibration changes, which just call `analyze` again
  with `replaceId`) work without server state. On wide screens the page is
  `100vh` with no body scroll; the health/diag cards scroll internally. At
  <=1300px it becomes a single scrolling column on purpose; the dialog uses
  `result.module_px_x`.
- `report.py` — `build_pdf` is used by the web service; it prints calibration
  (red warning + disclaimer), separates «Чтение: OK» from the quality verdict,
  adds the `Шкала 4/3/2/1` column, shows `res.symbology`, renders the GS1 table
  as AI/element/display value/description, optionally adds a «Сведения о товаре
  (Честный знак)» table when `crpt_info` is passed, and `build_history_pdf`
  builds the history export with read/GS1/quality columns.

## Versioning

`VERSION` in `version.py` (currently `1.0.52`) appears in the web header, CLI
`--version`, and PDF footer. Rules: bump **patch** after every `AGENTS.md`
edit, **minor** after a session with >30 user requests, **major** after >300.
`version.py` must be bumped alongside.

## Build and release

`build.spec` + `build.ps1` produce a single-file
`dist/DataMatrixVerifier.exe` (CLI/web in one). The spec bundles `webui/` and
`favicon.ico`, excludes torch/tkinter; `build/` and `dist/` are gitignored.
Releases are published with `gh release create v<version>` attaching the exe;
the tag must match `version.py`. Docker builds the web service only.
`deploy/docker-compose.yml` runs it as project `datamatrix` on the external
Caddy network (`deploy_default`, override with `WEB_NETWORK`); Caddy proxies
to `datamatrix:8501`. The Dockerfile installs `fonts-dejavu-core` so Cyrillic
PDF reports work on Linux (Windows fonts are tried first).

## Known gaps

- **Grade determination is the main remaining item.** `core/grade.py` is not
  calibrated to the Axicon reference; local `G0..G4` filename labels are the
  owner's reference grades, and our class often differs. Until a labeled
  calibration set exists, do not claim grade accuracy.
- No rule yet forces a read to be an error for very poor codes; e.g. local
  `samples/G_ERROR_9` still decodes here as class 0.
- Local samples `G0_5`, `G1_1`, `G1_2`, `G_ERROR_1`, `G_ERROR_3` and
  `samples/new_codes/G_ERROR_10` decode via no path (only `G_ERROR_3` reaches
  zxing, with a ChecksumError).
- Web history is browser-only (IndexedDB), so clearing site data loses it;
  `--web` has no auth (localhost by default) and stores nothing about uploads.

## Gotchas

- waitress has NO auto-reload: after editing `.py` or `webui/`, the old process
  keeps serving old code. A leftover server (possibly from another session) can
  sit on port 8010 and report a stale `/api/version`; check
  `Get-NetTCPConnection -LocalPort 8010` before debugging "changes don't apply".
- `cv2.imread` fails on Cyrillic paths; the CLI uses
  `verifier.imread_unicode` (`np.fromfile` + `imdecode`). Uploads are fine.
- Dotted/inverted decode runs only after normal decode fails, costs ~1 s per
  code (more when tiles run), and grades coarsely; product packs / dark
  backgrounds / strong perspective may still fail.
- `webui/` is served statically, so never write generated artifacts there.

## Chestny Znak (ЧЗ) — opt-in product lookup

The app **never calls ЧЗ automatically**. Only an explicit action (Web button
«Проверить в ЧЗ» or CLI `--crpt`) calls the undocumented public mobile endpoint:

```
POST https://mobile.api.crpt.ru/mobile/check
{"code": "<raw marking code>", "codeType": "datamatrix"}
```

The request mimics the iOS app headers (`User-Agent`/`client`); plain GET is
often rejected with 403. No token/auth is used. The endpoint may be geo-blocked
outside RU or change without notice; `crpt.py` raises `CrptError`, the UI shows
the message and the app keeps working offline. Never request on startup or
analysis, never log codes, and never send codes automatically. True API token
endpoints (`/cises/info`, `/product/info`, …) remain out of scope.

`crpt.parse_response()` normalizes `codeFounded`/`checkResult`/`status`/
`warning`, nested `<category>Data`, `catalogData` and dates; `lookup()` does the
network call. `raw` stays server-side and is stripped from the Web API,
CLI JSON and PDF. Web caches results in memory.
