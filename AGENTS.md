# AGENTS.md

Python app for **GS1 DataMatrix verification**: locate symbols in photos, decode
with zxing-cpp, grade print quality ISO/IEC 15415-style, show results in a
Tkinter GUI, a Flask web UI, or the CLI. All user-facing text (UI, CLI, PDF) is
Russian. Branch `master`; remote `origin` =
`https://github.com/lopatin2012/VerificatorDataMatrix.git`.

The working tree often carries uncommitted edits — run `git status` before
assuming it is clean. `README.md` is the (Russian) user documentation; update it
when user-facing behavior changes.

## Commands

Always invoke the repo venv explicitly. Bare `python` is the system 3.14.5 with
none of the app's deps — `README.md`'s claim that `python` resolves to the venv
is wrong in this checkout.

```
# smoke tests — the ONLY test suite (no pytest/unittest); CI runs this
.venv\Scripts\python.exe main.py --selftest

# GUI (also the default when none of --file/--dir/--web is given)
.venv\Scripts\python.exe main.py --gui

# one image / a directory of images
.venv\Scripts\python.exe main.py --file samples/G4_1.jpg
.venv\Scripts\python.exe main.py --dir test_image_codes

# web service (Flask app served by waitress)
.venv\Scripts\python.exe main.py --web --host 0.0.0.0 --port 8000

# Docker image runs the web service on :8501 (not 8000)
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
- `test_image_codes/` has 12 real product-pack photos. It is UNTRACKED but not
  `.gitignore`d, so a bare `git add .` stages it (only `.dockerignore` excludes
  it). Use it for manual decode checks.
- `webui/_report.pdf` is a stale 5.6 MB untracked leftover (current code writes
  PDFs to a temp dir). Because `webui/` is served statically it is publicly
  fetchable at `/_report.pdf`, and a bare `git add .` stages it — delete it.
- Use `-X utf8` when piping Cyrillic output to files (console may mojibake).
- `LICENSE` is MIT, Copyright (c) 2026 Maxim Lopatin; keep it and the README
  license section.

## Testing

`main.py --selftest` (`selftest.py`) is self-contained: GS1 parsing/validation
plus synthetic solid, dotted, and inverted DataMatrix decode (8 checks). Real
images are not in git, so still verify decode/geometry changes manually against
`test_image_codes/` or the owner's `samples/`. CI
(`.github/workflows/ci.yml`) runs the same command on Ubuntu after installing
`libgl1`/`libglib2.0-0`.

## Architecture

- `main.py` — argparse entry: GUI, web, CLI, selftest. Defaults to GUI.
- `verifier.analyze_all(img)` is the pipeline entry: decode + grid + grades +
  GS1 for **every** symbol, returning a list of `Result` sorted best-first
  (decoded/higher grade first); `analyze(img)` returns the first or an error
  Result. `to_dict()` is the JSON shape; `score_of`, `is_good`,
  `plain_content`, and `problem_regions` live here too.
- `core/decode.py` — `decode_all` returns one `DecodeResult` per symbol,
  deduped by quad. zxing gets an RGB image, and gray comes from
  `cvtColor(BGR2GRAY)` — **never** `cv2.imread(..., IMREAD_GRAYSCALE)`, which
  yields different pixels on this machine and breaks zxing. Tries raw color,
  then thresholded passes (96/128/160/192), then grid rebuild + `is_pure`.
  Undecoded but located symbols are kept for grading only if the quad is
  plausible (>= 8 modules/side, >= 24 px, aspect <= 5, <= 80% of frame) and the
  L+timing pattern score is strong — the run-based locator emits whole-frame
  and tiny (4x4) false positives.
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
  and perspective-warp grid extraction; tries both polarities.
- `core/nn_locator.py` — optional ResNet18 corner regressor, lazy `torch`
  import; missing torch is silently ignored. Last-resort crop-then-decode.
- `core/grade.py` — parameter grades 0–4, overall = minimum. Thresholds are
  approximate (see Known gaps). Parameter names are exact Russian strings that
  `problem_regions` and the UI match; renaming one silently breaks the heatmap.
- `gs1.py` — parses AIs from raw bytes or HRI; `validate()` returns warnings
  (unknown AI, fixed-length mismatch, GTIN/SSCC mod-10), surfaced as
  `Result.gs1_warnings`.
- Copy paths preserve the GS separator `\x1d` (only FS `\x1c`/RS `\x1e` are
  stripped): `plain_content()` feeds `content_raw`/`content_plain`. GUI and web
  copy the raw string and only render `[GS]` on screen. Don't strip `\x1d` —
  it is required to re-parse variable-length AIs.
- `webapp.py` + `webui/` — Flask/waitress. REST: `/api/analyze` (returns
  `{image, results:[...]}`, one `result_id` per code; with no code it still
  returns `image` plus `error`), `/api/history`, `/api/history/clear`,
  `/api/result/<id>`, `/api/history.csv`, `/api/history.txt`,
  `/api/history.pdf`, `/api/pdf`, `/api/version`. Entries are an in-memory
  LRU of 50 (`{res, img, payload, thumb, ts}`), so ids 404 once evicted and
  history dies with the process. `history.txt` is one decoded code per line
  (`content_plain`, real GS separators, CRLF); undecoded entries are skipped.
  Upload cap is 25 MB (`MAX_CONTENT_LENGTH`). PDFs go to `PDF_DIR` (a temp
  dir), never `webui/`. `@app.after_request` sets `Cache-Control: no-store`.
- `report.py` — `build_pdf` is used by both the web service and the GUI button;
  `build_history_pdf` builds the history export. `ui.py` draws its own overlays
  and shows a "Код не найден" banner; its "Экспорт TXT" button writes
  `scan_log` (all decoded contents this session, consecutive duplicates
  collapsed) as UTF-8 CRLF, one code per line.

## Versioning

`VERSION` in `version.py` (currently `1.0.33`) appears in the window title, CLI
`--version`, and PDF footer. Rules: bump **patch** after every `AGENTS.md`
edit, **minor** after a session with >30 user requests, **major** after >300.
`version.py` must be bumped alongside.

## Build and release

`build.spec` + `build.ps1` produce a single-file
`dist/DataMatrixVerifier.exe` (GUI/CLI/web in one). The spec bundles `webui/`
and `favicon.ico` and excludes torch; `build/` and `dist/` are gitignored.
Releases are published with `gh release create v<version>` attaching the exe;
the tag must match `version.py`. Docker builds the web service only.

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
- Web history is in-memory only; `--web` has no auth (localhost by default).

## Gotchas

- waitress has NO auto-reload: after editing `.py` or `webui/`, the old process
  keeps serving old code. A leftover server (possibly from another session) can
  sit on port 8000 and report a stale `/api/version`; check
  `Get-NetTCPConnection -LocalPort 8000` before debugging "changes don't apply".
- `cv2.imread` fails on Cyrillic paths; the CLI/GUI use
  `verifier.imread_unicode` (`np.fromfile` + `imdecode`). Uploads are fine.
- Dotted/inverted decode runs only after normal decode fails, costs ~1 s per
  code (more when tiles run), and grades coarsely; product packs / dark
  backgrounds / strong perspective may still fail.
- `webui/` is served statically, so never write generated artifacts there.

## Chestny Znak (ЧЗ) — offline by design

The app deliberately never calls ЧЗ; no integration should be added casually.
From `docs/` (gitignored): there is **no token-free way** to look up product
info by DataMatrix code — `/cises/info`, `/cises/list`, `/product/info` all need
`Authorization: Bearer <token>`, and the token requires a participant account.
Only `/participants?inns=...` and `/edo/inn/{inn}` are token-free and return no
product data. If such a feature is ever wanted it must be opt-in, require
credentials/network, and never be on by default.
