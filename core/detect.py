import cv2
import numpy as np
import zxingcpp
from PIL import Image


class Symbol:
    def __init__(self):
        self.corners = None      # 4x2 quad (image coords)
        self.rows = 0
        self.cols = 0
        self.module_px = 0.0
        self.grid = None         # bool (rows x cols) dark/light, canonical
        self.reflectance = None  # float (rows x cols)
        self.inverted = False
        self.l_corner = None     # 'tl' | 'tr' | 'bl' | 'br'


def _binarize(gray):
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bw


# ---------------------------------------------------------------- detection

def locate_candidates(gray, max_results=4):
    """Candidate symbol quads using zxing (positions also for failed decodes)."""
    im = Image.fromarray(gray)
    quads = []
    res = zxingcpp.read_barcodes(
        im, formats=zxingcpp.BarcodeFormat.DataMatrix,
        try_rotate=True, return_errors=True)
    for b in res:
        pts = np.array(
            [(p.x, p.y) for p in (b.position.top_left, b.position.top_right,
                                  b.position.bottom_right, b.position.bottom_left)],
            dtype=np.float32)
        quads.append(_order_quad(pts))
    return quads[:max_results]


def _order_quad(pts):
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    return pts[np.argsort(ang)]


def find_symbol(gray, known_size=None):
    """Locate + reconstruct. Returns Symbol or None."""
    best = None
    for invert in (False, True):
        g = 255 - gray if invert else gray
        for q in locate_candidates(g):
            sym = extract_grid(gray, q, known_size=known_size)
            if sym is not None:
                sym.inverted = invert
                if best is None or sym.rows * sym.cols > best.rows * best.cols:
                    best = sym
        if best is None:
            for quad in _locate_by_l(g):
                sym = extract_grid(gray, quad, known_size=known_size)
                if sym is not None:
                    sym.inverted = invert
                    if best is None or sym.rows * sym.cols > best.rows * best.cols:
                        best = sym
    return best


def _locate_by_l(gray, max_results=3):
    """Find candidate symbol quads by detecting the L pattern via long runs
    (fallback when zxing reports no position)."""
    best = []
    for g in (gray, 255 - gray):
        cands = _locate_by_l_impl(g)
        for c in cands:
            sym = extract_grid(gray, c, known_size=(22, 22))
            if sym is None:
                continue
            score = _pattern_score(sym)
            best.append((score, c))
    best.sort(key=lambda t: t[0], reverse=True)
    return [c for _, c in best[:max_results]]


def _locate_by_l_impl(gray, min_len=60):
    """Find L-pattern corner candidates in a full image via long runs."""
    bw = _binarize(gray)
    H, W = bw.shape
    dark = bw < 128

    # Rows with a long dark run, and columns with a long dark run.
    row_runs = []
    for y in range(0, H, 2):
        run = _longest_run(dark[y, :])
        if run and run[1] - run[0] >= min_len:
            row_runs.append((y, run))
    col_runs = []
    for x in range(0, W, 2):
        run = _longest_run(dark[:, x])
        if run and run[1] - run[0] >= min_len:
            col_runs.append((x, run))

    if not row_runs or not col_runs:
        return []

    # L corner: a row-run and a col-run sharing an endpoint.
    quads = []
    for y, (rx0, rx1) in row_runs:
        for x, (cy0, cy1) in col_runs:
            if not (abs(rx0 - x) <= 3 or abs(rx1 - x) <= 3):
                continue
            if not (abs(cy0 - y) <= 3 or abs(cy1 - y) <= 3):
                continue
            # horizontal run is on the left or right edge of the symbol?
            h_left = abs(rx0 - x) <= 3
            v_top = abs(cy0 - y) <= 3
            x0, x1 = rx0, rx1
            y0, y1 = cy0, cy1
            if h_left and v_top:      # corner at top-left
                corners = [(x, y), (x1, y), (x1, y1), (x, y1)]
            elif not h_left and v_top:  # corner at top-right
                corners = [(x, y), (x, y1), (x0, y1), (x0, y)]
            elif h_left:                # corner at bottom-left
                corners = [(x, y1), (x, y), (x1, y), (x1, y1)]
            else:                       # corner at bottom-right
                corners = [(x1, y1), (x0, y1), (x0, y), (x1, y)]
            quads.append(np.array(corners, dtype=np.float32))
    return quads


def _pattern_score(sym):
    """How well the grid matches the L + timing fixed pattern."""
    grid = sym.grid
    n_rows, n_cols = grid.shape
    if n_rows < 4 or n_cols < 4:
        return 0.0
    l_solid = float(grid[:, 0].mean())
    b_solid = float(grid[-1, :].mean())
    top_alt = float((grid[0, 1:] != grid[0, :-1]).mean())
    right_alt = float((grid[1:, -1] != grid[:-1, -1]).mean())
    return 0.5 * (l_solid + b_solid) + 0.5 * (top_alt + right_alt) / 2.0



# ---------------------------------------------------------- grid extraction

def extract_grid(gray, corners, warp_size=800, known_size=None):
    corners = np.asarray(corners, dtype=np.float32).reshape(4, 2)
    quad = _order_quad(corners)
    dst = np.array([[0, 0], [warp_size, 0], [warp_size, warp_size], [0, warp_size]],
                   dtype=np.float32)
    M = cv2.getPerspectiveTransform(quad, dst)
    warped = cv2.warpPerspective(gray, M, (warp_size, warp_size))
    Minv = np.linalg.inv(M)
    bw = _binarize(warped)

    info = _find_l(bw)
    inverted = False
    if info is None:
        inv_warp = 255 - warped
        bw = _binarize(inv_warp)
        info = _find_l(bw)
        inverted = True
    if info is None:
        return None
    corner_name, rect = info
    x0, y0, x1, y1 = rect

    table = {
        "tl": 1, "tr": 2, "bl": 0, "br": 3,
    }
    ori = table[corner_name]

    # canonical rect (rotate symbol rect corners). rot90 maps (x,y) ->
    # (y, W-1-x) for k=1, (W-1-x, W-1-y) for k=2, (W-1-y, x) for k=3.
    r = _rotate_rect((x0, y0, x1 - x0, y1 - y0), ori, warp_size)
    cr = (r[0], r[1], r[0] + r[2], r[1] + r[3])

    if known_size is not None:
        n_rows, n_cols = known_size
        if n_rows < 4 or n_cols < 4 or n_rows > 150 or n_cols > 150:
            return None
    else:
        n_rows, n_cols = _module_counts(bw, ori, cr, warp_size)
        if n_rows is None:
            return None

    c_x0, c_y0, c_x1, c_y1 = cr
    mod = max((c_x1 - c_x0) / n_cols, (c_y1 - c_y0) / n_rows)

    # Sample per-module reflectance by averaging the warped grayscale over
    # each module cell in the canonical frame.
    cwarped = np.rot90(warped, ori)
    ref = np.zeros((n_rows, n_cols), dtype=np.float64)
    cell_w = (c_x1 - c_x0) / n_cols
    cell_h = (c_y1 - c_y0) / n_rows
    for row in range(n_rows):
        for col in range(n_cols):
            cy0 = int(c_y0 + row * cell_h)
            cy1 = int(c_y0 + (row + 1) * cell_h)
            cx0 = int(c_x0 + col * cell_w)
            cx1 = int(c_x0 + (col + 1) * cell_w)
            cy0 = max(0, min(cwarped.shape[0] - 1, cy0))
            cy1 = max(cy0 + 1, min(cwarped.shape[0], cy1))
            cx0 = max(0, min(cwarped.shape[1] - 1, cx0))
            cx1 = max(cx0 + 1, min(cwarped.shape[1], cx1))
            ref[row, col] = cwarped[cy0:cy1, cx0:cx1].mean()

    sym = Symbol()
    sym.corners = quad
    sym.rows = n_rows
    sym.cols = n_cols
    sym.module_px = mod
    sym.orientation = ori
    sym.reflectance = ref
    thresh = _otsu_1d(ref)
    sym.grid = ref < thresh if not inverted else ref > thresh
    sym.l_corner = corner_name
    sym.inverted = inverted
    return sym


def _find_l(bw, thr=0.8):
    """Find the L pattern in the warped binary image.

    Returns (corner_name, (x0, y0, x1, y1)) or None.
    """
    H, W = bw.shape
    dark = bw < 128
    rowsum = dark.mean(axis=1)
    colsum = dark.mean(axis=0)

    # horizontal arm band: contiguous rows that are almost fully dark
    hrows = _plateaus(np.where(rowsum > thr)[0])
    vcols = _plateaus(np.where(colsum > thr)[0])
    if not hrows or not vcols:
        return None
    hy0, hy1 = max(hrows, key=lambda r: r[1] - r[0])
    vx0, vx1 = max(vcols, key=lambda r: r[1] - r[0])

    # horizontal arm run: longest dark run on a row inside the band
    row = int((hy0 + hy1) // 2)
    hx0, hx1 = _longest_run(bw[row, :])
    # vertical arm run: longest dark run on a col inside the band
    col = int((vx0 + vx1) // 2)
    vy0, vy1 = _longest_run(bw[:, col])

    if hx0 is None or vy0 is None:
        return None

    h_top = hy0 < H / 2
    v_left = vx0 < W / 2
    name = ("t" if h_top else "b") + ("l" if v_left else "r")
    if name not in ("tl", "tr", "bl", "br"):
        return None

    x0, x1 = hx0, hx1   # symbol left/right edges
    y0, y1 = vy0, vy1   # symbol top/bottom edges
    return name, (x0, y0, x1, y1)


def _plateaus(idxs):
    if idxs.size == 0:
        return []
    out = []
    start = prev = idxs[0]
    for v in idxs[1:]:
        if v == prev + 1:
            prev = v
        else:
            out.append((int(start), int(prev)))
            start = prev = v
    out.append((int(start), int(prev)))
    return out


def _longest_run(line):
    dark = line < 128
    best = None
    n = 0
    start = None
    for i, v in enumerate(dark):
        if v:
            if start is None:
                start = i
        else:
            if start is not None:
                if best is None or i - start > best[1] - best[0]:
                    best = (start, i)
                start = None
    if start is not None:
        if best is None or len(dark) - start > best[1] - best[0]:
            best = (start, len(dark))
    return best


def _module_counts(bw, ori, canonical_rect, W):
    """Count modules from the timing borders (top + right in canonical)."""
    x0, y0, x1, y1 = canonical_rect
    widths = []
    heights = []
    for dy in range(1, 4):
        if y0 + dy < y1:
            wx0, wy0 = _unrotate(x0, y0 + dy, ori, W)
            wx1, wy1 = _unrotate(x1, y0 + dy, ori, W)
            line = _sample_line(bw, wx0, wy0, wx1, wy1)
            widths.append(_best_count(line, x1 - x0))
    for dx in range(1, 4):
        if x1 - dx > x0:
            wx0, wy0 = _unrotate(x1 - dx, y0, ori, W)
            wx1, wy1 = _unrotate(x1 - dx, y1, ori, W)
            line = _sample_line(bw, wx0, wy0, wx1, wy1)
            heights.append(_best_count(line, y1 - y0))
    if not widths or not heights:
        return None, None
    n_cols = _median_int(widths)
    n_rows = _median_int(heights)
    if n_cols < 4 or n_rows < 4 or n_cols > 150 or n_rows > 150:
        return None, None
    return n_rows, n_cols


def _best_count(line, extent):
    """Find N (module count) that best fits the alternating timing pattern.

    The timing pattern is a perfect D/L/D/L... sequence (starting dark).
    Score each even N by how well a grid of N modules matches that sequence.
    """
    if extent <= 0:
        return 0
    vals = (line < 128).astype(np.int8)
    best_n = 0
    best_score = -1
    for n in range(4, 151, 2):
        m = extent / n
        expected = np.tile([1, 0], (n + 1) // 2)[:n]
        score = 0.0
        ok = True
        for i in range(n):
            pos = int(round((i + 0.5) * m))
            pos = max(0, min(len(vals) - 1, pos))
            if vals[pos] == expected[i]:
                score += 1
            else:
                ok = False
        score /= n
        if score > best_score:
            best_score = score
            best_n = n
    if best_score < 0.5:
        return 0
    return best_n


def _median_int(values):
    vals = [v for v in values if v > 0]
    if not vals:
        return 0
    return int(round(float(np.median(vals))))


def _sample_line(img, x0, y0, x1, y1):
    n = max(int(np.hypot(x1 - x0, y1 - y0)), 2)
    xs = np.linspace(x0, x1, n).astype(int)
    ys = np.linspace(y0, y1, n).astype(int)
    xs = np.clip(xs, 0, img.shape[1] - 1)
    ys = np.clip(ys, 0, img.shape[0] - 1)
    return img[ys, xs]



def _rotate_rect(rect, k, W):
    x, y, w, h = rect
    if k == 0:
        return rect
    if k == 1:
        return (y, W - 1 - x - w, h, w)
    if k == 2:
        return (W - 1 - x - w, W - 1 - y - h, w, h)
    if k == 3:
        return (W - 1 - y - h, x, h, w)


def _unrotate(wx, wy, k, W):
    if k == 0:
        return wx, wy
    if k == 1:
        return W - 1 - wy, wx
    if k == 2:
        return W - 1 - wx, W - 1 - wy
    return wy, W - 1 - wx


def _otsu_1d(values):
    """Otsu threshold for a 1-D array of intensities."""
    v = values.astype(np.float64)
    hist = np.histogram(v, bins=256, range=(0, 256))[0]
    tot = hist.sum()
    if tot == 0:
        return float(v.mean())
    w = np.cumsum(hist)
    m = np.cumsum(hist * np.arange(256))
    mu = m[-1] / tot
    best_t = 0
    best_var = -1
    for t in range(256):
        wb = w[t]
        if wb == 0 or wb == tot:
            continue
        mb = m[t] / wb
        wf = tot - wb
        mf = (m[-1] - m[t]) / wf
        var = wb * wf * (mb - mf) ** 2
        if var > best_var:
            best_var = var
            best_t = t
    return float(best_t)


# ------------------------------------------------------------------ output

def grid_to_image(sym, scale=10):
    img = np.full((sym.rows * scale, sym.cols * scale), 255, dtype=np.uint8)
    for r in range(sym.rows):
        for c in range(sym.cols):
            if sym.grid[r, c]:
                img[r*scale:(r+1)*scale, c*scale:(c+1)*scale] = 0
    return img