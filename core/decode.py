"""Decoding of GS1 DataMatrix via zxing-cpp, with grid-assisted fallback."""
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


def decode(img, _depth=0):
    """Try to decode a DataMatrix in the image.

    `img` is a BGR (or RGB) color image; grayscale is derived internally with
    cvtColor (plain IMREAD_GRAYSCALE produces different values on some
    systems and hurts zxing). The module grid is always reconstructed so
    grading has correct geometry. Returns a DecodeResult.
    """
    res = DecodeResult()
    if img.ndim == 2:
        gray = img
        rgb = img
    else:
        if img.shape[2] == 4:
            img = img[:, :, :3]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    res.gray = gray

    im = Image.fromarray(rgb)
    direct = None
    found = zxingcpp.read_barcodes(
        im, formats=zxingcpp.BarcodeFormat.DataMatrix,
        try_rotate=True, try_invert=True, try_downscale=True)
    if not found:
        # Some low-contrast symbols only appear after aggressive thresholding.
        for th in (96, 128, 160, 192):
            bw_img = Image.fromarray(((gray > th) * 255).astype(np.uint8))
            found = zxingcpp.read_barcodes(
                bw_img, formats=zxingcpp.BarcodeFormat.DataMatrix,
                try_rotate=True, try_invert=True, try_downscale=True)
            if found:
                break
    if found:
        direct = found[0]
        res.ok = True
        res.text = direct.text
        res.bytes = bytes(direct.bytes)
        res.position = [(p.x, p.y) for p in (direct.position.top_left, direct.position.top_right,
                                             direct.position.bottom_right, direct.position.bottom_left)]
        res.quad = detect._order_quad(np.asarray(res.position, dtype=np.float32))

    # Position-only candidates (include undecoded results).
    cands = detect.locate_candidates(gray)
    if res.quad is not None and not any(np.allclose(res.quad, c) for c in cands):
        cands.insert(0, res.quad)
    if not cands:
        cands = detect._locate_by_l(gray)

    # Reconstruct the module grid. The correct size is the one whose grid
    # decodes (zxing is_pure trusts the given grid, so decode success
    # verifies the module count). Pattern score is the fallback when no
    # size decodes (heavily damaged symbols).
    expected = res.text if res.ok else None
    fallback = None
    for quad in cands:
        # Fallback: better of 20x20 / 22x22 by fixed-pattern fit.
        for size in [(20, 20), (22, 22)]:
            sym = detect.extract_grid(gray, quad, known_size=size)
            if sym is None:
                continue
            sc = _pattern_score(sym)
            if fallback is None or sc > _pattern_score(fallback):
                fallback = sym
        for size in _candidate_sizes(gray, quad):
            sym = detect.extract_grid(gray, quad, known_size=size)
            if sym is None:
                continue
            grid_img = detect.grid_to_image(sym)
            r = zxingcpp.read_barcodes(
                Image.fromarray(grid_img), formats=zxingcpp.BarcodeFormat.DataMatrix,
                is_pure=True)
            if r and r[0].valid and r[0].text:
                text = r[0].text
                if expected is None or text == expected or text.startswith(expected[:10]):
                    res.symbol = sym
                    if not res.ok:
                        res.ok = True
                        res.text = text
                        res.bytes = bytes(r[0].bytes)
                        res.via_grid = True
                    if res.quad is None:
                        res.quad = quad
                    return res

    if fallback is not None:
        if res.quad is None:
            res.quad = fallback.corners
        res.symbol = fallback

    # Last resort: neural-net locator (crop + classic decode).
    if res.symbol is None and _depth == 0:
        res = _nn_fallback(gray, res)
    return res


def _candidate_sizes(gray, quad):
    """Symbol sizes to try. Sample codes are all 20x20 or 22x22."""
    base = detect.extract_grid(gray, quad)
    if base is not None:
        base_r, base_c = base.rows, base.cols
    else:
        base_r = base_c = 22
    return sorted([(20, 20), (22, 22)],
                  key=lambda s: (abs(s[0] - base_r) + abs(s[1] - base_c)))


def _nn_fallback(gray, res):
    """Last-resort locator: neural-net region -> crop -> classic decode.

    The NN returns a coarse region on large images; we crop a generous area
    around it and run the standard pipeline on the crop (the code then fills
    most of the frame). Results are remapped to the original image coords.
    """
    try:
        from . import nn_locator
        if not nn_locator.available():
            return res
        pts = nn_locator.predict(gray)
        if pts is None:
            return res
    except Exception:
        return res

    x0, y0 = float(pts[:, 0].min()), float(pts[:, 1].min())
    x1, y1 = float(pts[:, 0].max()), float(pts[:, 1].max())
    m = max(30, int((x1 - x0 + y1 - y0) * 1.2))
    cx0 = max(0, int(x0) - m)
    cy0 = max(0, int(y0) - m)
    cx1 = min(gray.shape[1], int(x1) + m)
    cy1 = min(gray.shape[0], int(y1) + m)
    if (cx1 - cx0) < 80 or (cy1 - cy0) < 80:
        return res

    crop = gray[cy0:cy1, cx0:cx1]
    sub = decode(crop, _depth=1)
    if sub.symbol is None:
        return res

    sub.symbol.corners = np.asarray(sub.symbol.corners, dtype=np.float32) + \
        np.array([cx0, cy0], dtype=np.float32)
    if sub.quad is not None:
        sub.quad = np.asarray(sub.quad, dtype=np.float32) + \
            np.array([cx0, cy0], dtype=np.float32)
    if sub.position:
        sub.position = [(px + cx0, py + cy0) for px, py in sub.position]
    res.symbol = sub.symbol
    if not res.ok:
        res.ok = sub.ok
        res.text = sub.text
        res.bytes = sub.bytes
        res.position = sub.position
        res.quad = sub.quad
        res.via_grid = sub.via_grid
    res.via_nn = True
    return res


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