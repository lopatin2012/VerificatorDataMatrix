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


def _symbol_for_quad(gray, quad, expected):
    """Reconstruct the module grid for a candidate quad.

    Tries is_pure decoding over candidate sizes (decode success confirms the
    module count). Falls back to the best fixed-pattern fit for heavily
    damaged symbols. Returns (sym, text, bytes, via_grid).
    """
    base = detect.extract_grid(gray, quad)
    base_size = (base.rows, base.cols) if (base is not None
                                           and base.rows >= 8 and base.cols >= 8) else None
    fallback = base
    fallback_sc = _pattern_score(base) if base is not None else -1.0
    for size in _candidate_sizes(base):
        if base_size is not None and size == base_size:
            sym = base
        else:
            sym = detect.extract_grid(gray, quad, known_size=size)
        if sym is None:
            continue
        sc = _pattern_score(sym)
        if sc > fallback_sc:
            fallback, fallback_sc = sym, sc
        grid_img = detect.grid_to_image(sym)
        r = zxingcpp.read_barcodes(
            Image.fromarray(grid_img), formats=zxingcpp.BarcodeFormat.DataMatrix,
            is_pure=True)
        if r and r[0].valid and r[0].text:
            text = r[0].text
            if expected is None or text == expected or text.startswith(expected[:10]):
                return sym, text, bytes(r[0].bytes), True
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

    candidates = []  # (quad, text, bytes, position)

    def add_candidate(quad, text=None, byt=None, position=None):
        quad = detect._order_quad(np.asarray(quad, dtype=np.float32).reshape(4, 2))
        for q, *_ in candidates:
            if _quads_close(q, quad):
                return
        candidates.append((quad, text, byt, position))

    # Direct decodes on raw color (all of them, not just the first).
    found = zxingcpp.read_barcodes(
        im, formats=zxingcpp.BarcodeFormat.DataMatrix,
        try_rotate=True, try_invert=True, try_downscale=True)
    for b in found:
        quad = _barcode_quad(b)
        add_candidate(quad, b.text, bytes(b.bytes),
                      [(p.x, p.y) for p in (b.position.top_left, b.position.top_right,
                                            b.position.bottom_right, b.position.bottom_left)])

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
                                                b.position.bottom_right, b.position.bottom_left)])

    # Position-only candidates (include undecoded results) + run-based L locator.
    for q in detect.locate_candidates(gray):
        add_candidate(q)
    for q in detect._locate_by_l(gray):
        add_candidate(q)

    results = []
    frame_w, frame_h = gray.shape[1], gray.shape[0]
    for quad, text, byt, position in candidates:
        # Skip obviously-bogus position-only quads before the size search.
        if text is None and not _plausible_quad(quad, frame_w, frame_h):
            continue
        sym, gtext, gbytes, via_grid = _symbol_for_quad(gray, quad, expected=text)
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


def _pattern_score(sym):
    """How well the grid matches the fixed pattern (L + timing) at its size.

    At the correct module count the bottom row and left column are solid
    (L pattern) and the top row / right column alternate (timing). A wrong
    count degrades these fractions sharply.
    """
    grid = sym.grid
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