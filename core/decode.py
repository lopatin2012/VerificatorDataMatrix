"""Decoding of GS1 DataMatrix via zxing-cpp, with grid-assisted fallback.

decode_all() finds EVERY DataMatrix in the image (not just the first);
decode() keeps the single-code behavior for callers that want the first one.
"""
import cv2
import numpy as np
import zxingcpp
from PIL import Image

from . import detect


class DecodeResult:
    def __init__(self):
        self.ok = False
        self.text = None
        self.bytes = None
        self.position = None
        self.quad = None
        self.symbol = None
        self.via_grid = False
        self.gray = None


def _prep(img):
    """Derive grayscale + RGB from a BGR (or grayscale) image.

    Grayscale is derived internally with cvtColor (plain IMREAD_GRAYSCALE
    produces different values on some systems and hurts zxing).
    """
    if img.ndim == 2:
        gray = img
        rgb = img
    else:
        if img.shape[2] == 4:
            img = img[:, :, :3]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return gray, rgb


def _quads_close(a, b, tol_frac=0.2):
    """True if two quads (4x2 arrays) refer to the same symbol."""
    ca = np.asarray(a, dtype=np.float32).reshape(4, 2).mean(axis=0)
    cb = np.asarray(b, dtype=np.float32).reshape(4, 2).mean(axis=0)
    dist = float(np.hypot(ca[0] - cb[0], ca[1] - cb[1]))
    if dist < 12.0:
        return True
    size = float(np.abs(np.asarray(b, dtype=np.float32) - np.asarray(a, dtype=np.float32)).max())
    return dist < tol_frac * size


def _barcode_quad(b):
    pts = np.asarray(
        [(p.x, p.y) for p in (b.position.top_left, b.position.top_right,
                              b.position.bottom_right, b.position.bottom_left)],
        dtype=np.float32)
    return detect._order_quad(pts)


def _barcode_size(b):
    """Exact module count from zxing's own rendering of the decoded symbol.

    `Barcode.to_image(scale=1)` draws the symbol at 1 px/module on a light
    quiet zone, so the bounding box of its dark modules is the module grid.
    Used as a size hint so the rebuilt grid has the correct geometry (a wrong
    module count can still decode, e.g. a 20x4 grid for a 22x22 symbol).
    """
    try:
        a = np.asarray(b.to_image(scale=1))
    except Exception:
        return None
    dark = a < 128
    if not dark.any():
        return None
    ys, xs = np.where(dark)
    rows = int(ys.max() - ys.min() + 1)
    cols = int(xs.max() - xs.min() + 1)
    if not (8 <= rows <= 150 and 8 <= cols <= 150):
        return None
    return (rows, cols)


def _scaled_quad(quad, f):
    q = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    c = q.mean(axis=0)
    return (q - c) * f + c


def _candidate_sizes(base):
    """Even symbol sizes to try, near the auto-detected module count plus the
    common 20x20 / 22x22. Sorted by distance from the base size so the most
    likely size is tried first.
    """
    base_r = base_c = None
    if base is not None and base.rows >= 8 and base.cols >= 8:
        base_r, base_c = base.rows, base.cols

    sizes = {(20, 20), (22, 22)}
    if base_r is not None:
        for dr in range(-4, 5):
            for dc in range(-4, 5):
                r, c = base_r + dr, base_c + dc
                if 8 <= r <= 150 and 8 <= c <= 150 and r % 2 == 0 and c % 2 == 0:
                    sizes.add((r, c))

    def key(s):
        if base_r is None:
            return abs(s[0] - 20)
        return abs(s[0] - base_r) + abs(s[1] - base_c)

    return sorted(sizes, key=key)


def _grid_decodes(sym, expected):
    """is_pure decode of a rebuilt grid; returns (text, bytes) on a match."""
    grid_img = detect.grid_to_image(sym)
    r = zxingcpp.read_barcodes(
        Image.fromarray(grid_img), formats=zxingcpp.BarcodeFormat.DataMatrix,
        is_pure=True)
    if r and r[0].valid and r[0].text:
        text = r[0].text
        if expected is None or text == expected or text.startswith(expected[:10]):
            return text, bytes(r[0].bytes)
    return None, None


def _symbol_for_quad(gray, quad, expected, size_hint=None):
    """Reconstruct the module grid for a candidate quad.

    Tries is_pure decoding over candidate sizes (decode success confirms the
    module count). Falls back to the best fixed-pattern fit for heavily
    damaged symbols. Returns (sym, text, bytes, via_grid).
    """
    fallback = None
    fallback_sc = -1.0

    def consider(sym):
        nonlocal fallback, fallback_sc
        if sym is None:
            return None
        sc = _pattern_score(sym)
        if sc > fallback_sc:
            fallback, fallback_sc = sym, sc
        text, byt = _grid_decodes(sym, expected)
        if text is not None:
            return sym, text, byt, True
        return None

    # A successful zxing decode knows the exact module count; use it so the
    # rebuilt grid has the right geometry. A small expansion also absorbs the
    # half-module offset between zxing's quad and the module lattice.
    if size_hint is not None:
        best = None
        best_sc = -1.0
        for f in (1.0, 1.05, 1.03, 1.08, 0.97, 1.1):
            q = quad if f == 1.0 else _scaled_quad(quad, f)
            sym = detect.extract_grid(gray, q, known_size=size_hint)
            if sym is None:
                continue
            sc = _pattern_score(sym)
            if sc > best_sc:
                best, best_sc = sym, sc
            text, byt = _grid_decodes(sym, expected)
            if text is not None:
                return sym, text, byt, True
        if best is not None:
            # zxing decoded this symbol, so its module count is authoritative
            # even when our resampled grid does not decode (e.g. glare).
            return best, None, None, False

    base = detect.extract_grid(gray, quad)
    base_size = (base.rows, base.cols) if (base is not None
                                           and base.rows >= 8 and base.cols >= 8) else None
    for size in _candidate_sizes(base):
        if base_size is not None and size == base_size:
            got = consider(base)
        else:
            got = consider(detect.extract_grid(gray, quad, known_size=size))
        if got:
            return got
    return fallback, None, None, False


def _plausible_quad(quad, frame_w, frame_h):
    """Quick geometric sanity check for position-only (undecoded) quads, so
    the expensive module-size search is not spent on whole-frame or
    sub-pixel sliver false positives from the run-based locator.
    """
    c = np.asarray(quad, dtype=np.float32).reshape(4, 2)
    w = c[:, 0].max() - c[:, 0].min()
    h = c[:, 1].max() - c[:, 1].min()
    if min(w, h) < 24:
        return False
    if max(w, h) / max(1.0, min(w, h)) > 5.0:
        return False
    if w * h > 0.8 * frame_w * frame_h:
        return False
    return True


def _decode_impl(img, _depth):
    gray, rgb = _prep(img)
    im = Image.fromarray(rgb)

    candidates = []  # (quad, text, bytes, position, size)

    def add_candidate(quad, text=None, byt=None, position=None, size=None):
        quad = detect._order_quad(np.asarray(quad, dtype=np.float32).reshape(4, 2))
        for q, *_ in candidates:
            if _quads_close(q, quad):
                return
        candidates.append((quad, text, byt, position, size))

    # Direct decodes on raw color (all of them, not just the first).
    found = zxingcpp.read_barcodes(
        im, formats=zxingcpp.BarcodeFormat.DataMatrix,
        try_rotate=True, try_invert=True, try_downscale=True)
    for b in found:
        quad = _barcode_quad(b)
        add_candidate(quad, b.text, bytes(b.bytes),
                      [(p.x, p.y) for p in (b.position.top_left, b.position.top_right,
                                            b.position.bottom_right, b.position.bottom_left)],
                      _barcode_size(b))

    # Some low-contrast symbols only appear after aggressive thresholding.
    for th in (96, 128, 160, 192):
        bw_img = Image.fromarray(((gray > th) * 255).astype(np.uint8))
        found = zxingcpp.read_barcodes(
            bw_img, formats=zxingcpp.BarcodeFormat.DataMatrix,
            try_rotate=True, try_invert=True, try_downscale=True)
        for b in found:
            quad = _barcode_quad(b)
            add_candidate(quad, b.text, bytes(b.bytes),
                          [(p.x, p.y) for p in (b.position.top_left, b.position.top_right,
                                                b.position.bottom_right, b.position.bottom_left)],
                          _barcode_size(b))

    # Position-only candidates (include undecoded results) + run-based L locator.
    for q in detect.locate_candidates(gray):
        add_candidate(q)
    for q in detect._locate_by_l(gray):
        add_candidate(q)

    results = []
    frame_w, frame_h = gray.shape[1], gray.shape[0]
    for quad, text, byt, position, size in candidates:
        # Skip obviously-bogus position-only quads before the size search.
        if text is None and not _plausible_quad(quad, frame_w, frame_h):
            continue
        sym, gtext, gbytes, via_grid = _symbol_for_quad(
            gray, quad, expected=text, size_hint=size)
        if sym is None:
            continue
        dec = DecodeResult()
        dec.gray = gray
        dec.quad = quad
        dec.position = position
        dec.symbol = sym
        dec.ok = text is not None
        dec.text = text
        dec.bytes = byt
        dec.via_grid = via_grid
        if via_grid and not dec.ok:
            dec.ok = True
            dec.text = gtext
            dec.bytes = gbytes
        if dec.ok and dec.position is None:
            dec.position = quad.ravel().tolist()
        # Reject false positives from the run-based locator: an undecoded
        # symbol must be a plausible DataMatrix quad (not a whole-frame or
        # sub-pixel sliver) with a strong fixed pattern (L + timing).
        if not dec.ok:
            # No valid ECC200 symbol is smaller than 8 modules on a side, so
            # reject tiny pattern fits (the run-based locator emits 4x4 ones).
            if min(sym.rows, sym.cols) < 8:
                continue
            c = np.asarray(sym.corners, dtype=np.float32).reshape(4, 2)
            w = c[:, 0].max() - c[:, 0].min()
            h = c[:, 1].max() - c[:, 1].min()
            if min(w, h) < 24:
                continue
            if max(w, h) / max(1.0, min(w, h)) > 5.0:
                continue
            if w * h > 0.8 * frame_w * frame_h:
                continue
            if _pattern_score(sym) < 0.9:
                continue
        results.append(dec)

    # Dotted / low-contrast codes (e.g. white-on-dark): morphological closing
    # joins the dots so zxing can find the symbol. If the full frame sees no
    # symbol at all, the code is likely small, so retry on local tiles.
    if not any(r.ok for r in results):
        dotted, detected = _dotted_results(gray)
        if dotted:
            results = dotted
        elif not detected:
            tiled = _dotted_tiles(gray)
            if tiled:
                results = tiled

    # Last resort: neural-net locator (crop + classic decode).
    if not results and _depth == 0:
        results = _nn_fallback_all(gray)
    return results


def decode_all(img, _depth=0):
    """Decode ALL DataMatrix codes in the image.

    `img` is a BGR (or RGB) color image. Returns a list of DecodeResult,
    one per detected symbol (deduplicated by position). Undecoded but
    located symbols are included with symbol set and ok=False. Rotation is
    handled by zxing's try_rotate and by the L-pattern locator, so codes at
    any 90-degree multiple are found in a single pass.
    """
    return _decode_impl(img, _depth)


def decode(img, _depth=0):
    """Decode the first DataMatrix in the image. Returns a DecodeResult."""
    results = decode_all(img, _depth)
    if results:
        return results[0]
    return DecodeResult()


# ---- dotted / white-on-dark fallback ----

# Even ECC200 square sizes to try when rebuilding a dotted symbol's grid.
_DOT_MODULE_SIZES = tuple(range(10, 33, 2))
_DOT_CLOSE_KS = (3, 5, 7, 9, 11)
_DOT_WARP = 600
# Rebuilt grid must match the fixed pattern at least this well; below it the
# reconstruction is treated as a false positive (e.g. a photo of a screen).
_DOT_REBUILD_MIN_SCORE = 1.25


def _white_mask(gray):
    """Binary mask of the printed modules (works for white-on-dark codes)."""
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bw


def _dot_pitch(wmask):
    """Module pitch (modules per symbol side) from the dotted mask's
    periodicity, plus a prominence measure.

    Both axes' spectra must peak at the same period (within one module), else
    None is returned. A wrong module count can still pure-decode, so the pitch
    is used to pick the size that matches the symbol's own lattice.
    """
    dark = (wmask < 128).astype(np.float32)
    est = []
    for prof in (dark.mean(axis=0), dark.mean(axis=1)):
        p = prof - prof.mean()
        f = np.abs(np.fft.rfft(p)) ** 2
        fr = np.fft.rfftfreq(len(p), d=1.0 / _DOT_WARP)
        band = (fr >= 8) & (fr <= 34)
        if not band.any():
            return None
        fb, pb = fr[band], f[band]
        k = int(np.argmax(pb))
        prom = float(pb[k] / (np.median(pb) + 1e-9))
        est.append((float(fb[k]), prom))
    (p0, r0), (p1, r1) = est
    if abs(p0 - p1) > 1.0:
        return None
    return 0.5 * (p0 + p1), min(r0, r1)


def _pure_grid_text(grid, pad=3, scale=12):
    """Decode a canonical binary grid (True = dark module) via zxing is_pure."""
    img = np.where(grid, 0, 255).astype(np.uint8)
    img = cv2.copyMakeBorder(img, pad, pad, pad, pad,
                             cv2.BORDER_CONSTANT, value=255)
    img = cv2.resize(img, None, fx=scale, fy=scale,
                     interpolation=cv2.INTER_NEAREST)
    found = zxingcpp.read_barcodes(
        Image.fromarray(img), formats=zxingcpp.BarcodeFormat.DataMatrix,
        is_pure=True)
    for b in found:
        if b.valid and b.text:
            return b.text
    return None


def _dotted_warp(closed, quad):
    S = _DOT_WARP
    dst = np.array([[0, 0], [S, 0], [S, S], [0, S]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(np.asarray(quad, dtype=np.float32), dst)
    return cv2.warpPerspective(255 - closed, M, (S, S),
                               flags=cv2.INTER_LINEAR)


def _dotted_grid(wmask, n):
    cell = cv2.resize(wmask, (n, n), interpolation=cv2.INTER_AREA)
    _, bw = cv2.threshold(cell, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bw < 128


def _dotted_symbol(gray, closed, quad, n):
    """Build a Symbol for a dotted symbol's quad at module count `n`."""
    S = _DOT_WARP
    dst = np.array([[0, 0], [S, 0], [S, S], [0, S]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(np.asarray(quad, dtype=np.float32), dst)
    wgray = cv2.warpPerspective(gray, M, (S, S), flags=cv2.INTER_LINEAR)
    grid = _dotted_grid(_dotted_warp(closed, quad), n)
    ref = cv2.resize(wgray, (n, n),
                     interpolation=cv2.INTER_AREA).astype(np.float64)
    # grade.py expects dark modules to have low reflectance.
    if ref[grid].mean() > ref[~grid].mean():
        ref = 255.0 - ref
    sym = detect.Symbol()
    sym.corners = np.asarray(quad, dtype=np.float32)
    sym.rows = sym.cols = n
    q = np.asarray(quad, dtype=np.float32)
    side = 0.25 * sum(
        float(np.hypot(*(q[(i + 1) % 4] - q[i]))) for i in range(4))
    sym.module_px = side / n
    sym.grid = grid
    sym.reflectance = ref
    sym.inverted = True
    sym.l_corner = "bl"
    return sym


def _symbol_from_dotted(gray, closed, quad, expected):
    """Rebuild a Symbol for a dotted code from its zxing quad.

    `closed` is a binary image with printed modules white (255). zxing orders
    the quad corners in symbol coordinates, so the module lattice maps
    directly to canonical grid coordinates.
    """
    wmask = _dotted_warp(closed, quad)

    # Sizes whose rebuilt grid decodes to the text zxing already recovered.
    pure = {}
    for n in _DOT_MODULE_SIZES:
        g = _dotted_grid(wmask, n)
        if _pure_grid_text(g) == expected:
            pure[n] = _pattern_score_grid(g)

    # The dot pitch is the symbol's own lattice, so trust it over a pure
    # decode: a wrong module count can still decode (e.g. 32 for a 20x20
    # symbol), giving bogus geometry. No consistent pitch -> false positive.
    n = None
    pe = _dot_pitch(wmask)
    if pe is not None:
        pitch, _prom = pe
        n0 = max(_DOT_MODULE_SIZES[0],
                 min(_DOT_MODULE_SIZES[-1], int(round(pitch / 2.0) * 2)))
        if n0 in pure:
            n = n0
        else:
            near = [k for k in pure if abs(k - n0) <= 2]
            if near:
                n = min(near, key=lambda k: abs(k - n0))
            elif _pattern_score_grid(_dotted_grid(wmask, n0)) >= _DOT_REBUILD_MIN_SCORE:
                n = n0
    if n is None:
        return None
    return _dotted_symbol(gray, closed, quad, n)


def _symbol_from_dotted_tile(gray, closed, quad, expected):
    """Relaxed rebuild for a small, very low-grade dotted code found on a local
    crop. The full-frame dotted pass detected nothing at all, so the text zxing
    recovered is trusted and given the best-fitting module count (these codes
    are too degraded for the pitch to be measurable)."""
    sym = _symbol_from_dotted(gray, closed, quad, expected)
    if sym is not None:
        return sym
    wmask = _dotted_warp(closed, quad)
    best, best_sc = None, -1.0
    for n in _DOT_MODULE_SIZES:
        sc = _pattern_score_grid(_dotted_grid(wmask, n))
        if sc > best_sc:
            best, best_sc = n, sc
    if best is None:
        return None
    return _dotted_symbol(gray, closed, quad, best)


def _dotted_scan(gray, region, offset=(0, 0), relaxed=False,
                 kernels=_DOT_CLOSE_KS, scales=(1, 2)):
    """Closing + zxing over `region` (a crop of `gray` at `offset`).

    Returns (results, detected); `detected` is True if zxing found any symbol,
    even one whose grid could not be rebuilt (used to avoid tile fallbacks on
    screen/moire photos that the full-frame pass already sees).
    """
    ox, oy = offset
    base = _white_mask(region)
    detected = False
    for polarity in (base, 255 - base):
        for k in kernels:
            ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
            closed = cv2.morphologyEx(polarity, cv2.MORPH_CLOSE, ker)
            for scale in scales:
                img = closed if scale == 1 else cv2.resize(
                    closed, None, fx=scale, fy=scale,
                    interpolation=cv2.INTER_CUBIC)
                found = zxingcpp.read_barcodes(
                    Image.fromarray(img),
                    formats=zxingcpp.BarcodeFormat.DataMatrix,
                    try_rotate=True, try_invert=True, try_downscale=True)
                out = []
                for hit in found:
                    if not (hit.valid and hit.text):
                        continue
                    detected = True
                    quad = np.array(
                        [(p.x, p.y) for p in (
                            hit.position.top_left, hit.position.top_right,
                            hit.position.bottom_right,
                            hit.position.bottom_left)], dtype=np.float32) / scale
                    build = (_symbol_from_dotted_tile if relaxed
                             else _symbol_from_dotted)
                    sym = build(region, closed, quad, hit.text)
                    if sym is None:
                        continue
                    if ox or oy:
                        shift = np.array([ox, oy], dtype=np.float32)
                        sym.corners = np.asarray(sym.corners, np.float32) + shift
                        quad = quad + shift
                    dec = DecodeResult()
                    dec.gray = gray
                    dec.symbol = sym
                    dec.ok = True
                    dec.text = hit.text
                    dec.bytes = bytes(hit.bytes)
                    dec.position = [(float(x), float(y)) for x, y in quad]
                    dec.quad = detect._order_quad(quad)
                    dec.via_grid = True
                    out.append(dec)
                if out:
                    return out, detected
    return [], detected


def _dotted_results(gray):
    """Fallback for dotted / low-contrast codes (e.g. white-on-dark).

    Dot-style symbols defeat zxing's detector. Morphological closing joins the
    dots of adjacent dark modules without filling light modules, making the
    symbol readable. Runs only when the normal pipeline decoded nothing.
    """
    return _dotted_scan(gray, gray)


def _dotted_tiles(gray, tiles=(2, 2), overlap=0.25):
    """Last resort for small dotted codes the full-frame pass cannot see: scan
    overlapping tiles with a local (crop) Otsu threshold. Called only when the
    full-frame dotted pass detected no symbol at all, so screen/moire photos
    are not re-admitted here. Returns as soon as a symbol is found."""
    ni, nj = tiles
    H, W = gray.shape
    th, tw = H // ni, W // nj
    oy, ox = int(overlap * th), int(overlap * tw)
    for i in range(ni):
        for j in range(nj):
            y0 = max(0, i * th - oy); y1 = min(H, (i + 1) * th + oy)
            x0 = max(0, j * tw - ox); x1 = min(W, (j + 1) * tw + ox)
            crop = gray[y0:y1, x0:x1]
            if min(crop.shape) < 60:
                continue
            decs, _ = _dotted_scan(gray, crop, offset=(x0, y0), relaxed=True,
                                   kernels=(3, 5, 7), scales=(2, 3))
            if decs:
                return decs
    return []


def _pattern_score(sym):
    """How well the grid matches the fixed pattern (L + timing) at its size."""
    return _pattern_score_grid(sym.grid)


def _pattern_score_grid(grid):
    """Pattern fit of a bool grid (True = dark module).

    At the correct module count the bottom row and left column are solid
    (L pattern) and the top row / right column alternate (timing). A wrong
    count degrades these fractions sharply.
    """
    n_rows, n_cols = grid.shape
    if n_rows < 4 or n_cols < 4:
        return 0.0
    l_solid = float(grid[:, 0].mean())
    b_solid = float(grid[-1, :].mean())
    top_alt = float((grid[0, 1:] != grid[0, :-1]).mean())
    right_alt = float((grid[1:, -1] != grid[:-1, -1]).mean())
    return 0.5 * (l_solid + b_solid) + 0.5 * (top_alt + right_alt) / 2.0


def _nn_fallback_all(gray):
    """Last-resort locator: neural-net region -> crop -> classic decode.

    The NN returns a coarse region on large images; we crop a generous area
    around it and run the standard pipeline on the crop (the code then fills
    most of the frame). Results are remapped to the original image coords.
    """
    try:
        from . import nn_locator
        if not nn_locator.available():
            return []
        pts = nn_locator.predict(gray)
        if pts is None:
            return []
    except Exception:
        return []

    x0, y0 = float(pts[:, 0].min()), float(pts[:, 1].min())
    x1, y1 = float(pts[:, 0].max()), float(pts[:, 1].max())
    m = max(30, int((x1 - x0 + y1 - y0) * 1.2))
    cx0 = max(0, int(x0) - m)
    cy0 = max(0, int(y0) - m)
    cx1 = min(gray.shape[1], int(x1) + m)
    cy1 = min(gray.shape[0], int(y1) + m)
    if (cx1 - cx0) < 80 or (cy1 - cy0) < 80:
        return []

    crop = gray[cy0:cy1, cx0:cx1]
    sub_results = decode_all(crop, _depth=1)
    out = []
    for sub in sub_results:
        if sub.symbol is not None:
            sub.symbol.corners = np.asarray(sub.symbol.corners, dtype=np.float32) + \
                np.array([cx0, cy0], dtype=np.float32)
        if sub.quad is not None:
            sub.quad = np.asarray(sub.quad, dtype=np.float32) + \
                np.array([cx0, cy0], dtype=np.float32)
        if sub.position:
            sub.position = [(px + cx0, py + cy0) for px, py in sub.position]
        sub.via_nn = True
        out.append(sub)
    return out