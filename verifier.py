"""High-level verification pipeline for a DataMatrix image."""
import cv2
import numpy as np

from core import decode, detect, grade
from gs1 import is_gs1, parse, validate

# Standard reference apertures in microns (ISO 15415 selection).
STANDARD_APERTURES = [160, 200, 250, 318, 400, 500, 630]

# Used when the caller does not supply a calibration. Physical dimensions
# derived from it are flagged as approximate (see Result.calibration_default).
DEFAULT_UM_PER_PX = 10.0


def _calibration(um_per_px):
    """Return (value, is_default) for a user-supplied or missing calibration."""
    if um_per_px is None:
        return DEFAULT_UM_PER_PX, True
    value = float(um_per_px)
    if not value > 0:
        raise ValueError("um_per_px must be positive")
    return value, False


def fmt_ru(value, digits=0):
    """Format a number with a decimal comma (Russian UI convention)."""
    return f"{value:.{digits}f}".replace(".", ",")


def calibration_note(res):
    """Human-readable calibration status for reports."""
    value = fmt_ru(res.um_per_px or DEFAULT_UM_PER_PX, 2).rstrip("0").rstrip(",")
    suffix = " (по умолчанию)" if res.calibration_default else " (задана)"
    return f"Калибровка: {value} мкм/px{suffix}"


def calibration_warning(res):
    """Warning to show while the default calibration is in use."""
    if res.calibration_default:
        return ("Калибровка не задана: физические размеры и грейды "
                "ориентировочные.")
    return ""


def imread_unicode(path, flags=cv2.IMREAD_COLOR):
    """Read an image, tolerating non-ASCII (e.g. Cyrillic) paths.

    `cv2.imread` fails on such paths on Windows because of its narrow path
    handling; reading the bytes and decoding through `imdecode` avoids that.
    Returns None if the file cannot be read.
    """
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


class Result:
    def __init__(self):
        self.ok = False
        self.content = None
        self.content_raw = None
        self.symbology = "DataMatrix"
        self.min_grade = None
        self.min_reflectance = None
        self.max_reflectance = None
        self.um_per_px = None
        self.calibration_default = True
        self.module_px_x = None
        self.module_px_y = None
        self.x_dim_um = None
        self.y_dim_um = None
        self.print_growth_x = None
        self.print_growth_y = None
        self.aperture_um = None
        self.params = []
        self.elements = []
        self.gs1_warnings = []
        self.gs1_status = "none"       # ok | warn | none
        self.read_ok = False
        self.quality_ok = False
        self.quality_status = "unknown"  # good | bad | unknown
        self.overall_class = None
        self.class_code = None
        self.validation = "FAIL"       # legacy: decode status
        self.symbol = None
        self.corner_points = None
        self.error = None


def analyze(img, um_per_px=None):
    """Analyze one image (BGR color or grayscale). Returns a Result for the
    first detected DataMatrix, or a Result with error="Код не найден".

    `um_per_px=None` means the default 10 um/px; the result is then marked
    with `calibration_default=True`.
    """
    results = analyze_all(img, um_per_px)
    if results:
        return results[0]
    value, is_default = _calibration(um_per_px)
    res = Result()
    res.um_per_px = value
    res.calibration_default = is_default
    res.error = "Код не найден"
    return res


def analyze_all(img, um_per_px=None):
    """Analyze ALL DataMatrix codes found in one image.

    Returns a list of Result, one per detected symbol (deduplicated by
    position), sorted so the BEST reading comes first (highest grade,
    decoded before undecoded). Each Result grades its own symbol; undecoded
    symbols are included with validation="FAIL".
    """
    value, is_default = _calibration(um_per_px)
    results = []
    for dec in decode.decode_all(img):
        res = _analyze_one(img, dec, value, is_default)
        if res is not None:
            results.append(res)
    results.sort(key=lambda r: ((r.min_grade if r.min_grade is not None else 0.0),
                                r.validation == "OK"), reverse=True)
    return results


def _analyze_one(img, dec, um_per_px, calibration_default):
    res = Result()
    res.um_per_px = um_per_px
    res.calibration_default = calibration_default
    gray = getattr(dec, "gray", None)
    if gray is None:
        gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    sym = dec.symbol
    if sym is None and dec.quad is not None:
        sym = detect.extract_grid(gray, dec.quad)

    if sym is None:
        return None

    res.symbol = sym
    res.ok = True
    res.corner_points = sym.corners

    # Quiet zone needs the surrounding image (it lies outside the symbol
    # quad), so it is measured here once per final symbol rather than during
    # the many grid-rebuild attempts in the decoder.
    if getattr(sym, "quiet_zone", None) is None:
        try:
            sym.quiet_zone = detect.measure_quiet_zone(gray, sym)
        except Exception:
            sym.quiet_zone = None

    if dec.ok:
        res.content = dec.text
        res.content_raw = dec.bytes.decode("latin-1") if dec.bytes else None
        raw = dec.bytes if dec.bytes else (dec.text or "")
        elements = parse(raw)
        symid = getattr(dec, "symbology_id", "") or ""
        if is_gs1(raw, elements) or symid.startswith(("]d2", "]d5")):
            res.symbology = "GS1 DataMatrix"
            res.elements = elements
            res.gs1_warnings = validate(elements)
        else:
            # A plain DataMatrix (no FNC1 / no valid GS1 identifier) must not
            # be presented as GS1 or parsed into fake AIs.
            res.symbology = "DataMatrix"
            res.elements = []
            res.gs1_warnings = []

    params = grade.grade_symbol(sym, decoded=dec.ok)
    res.params = params

    # Physical module pitch per axis (sym.module_px_* is in source pixels;
    # this used to be the warp-space pitch, inflating dimensions ~5x).
    mod_x = getattr(sym, "module_px_x", 0.0) or sym.module_px
    mod_y = getattr(sym, "module_px_y", 0.0) or sym.module_px
    res.module_px_x = mod_x
    res.module_px_y = mod_y
    res.x_dim_um = mod_x * um_per_px
    res.y_dim_um = mod_y * um_per_px
    mod_um = 0.5 * (res.x_dim_um + res.y_dim_um)

    gx = gy = (0.0, 0.0)
    for p in params:
        if p.name == "Размерность печати X":
            gx = _parse_growth(p.value)
        elif p.name == "Размерность печати Y":
            gy = _parse_growth(p.value)
    res.print_growth_x = gx
    res.print_growth_y = gy

    res.min_grade = grade.overall_grade(params)
    res.aperture_um = _select_aperture(mod_um)

    ref = sym.reflectance
    if ref.size:
        res.min_reflectance = int(np.percentile(ref, 2))
        res.max_reflectance = int(np.percentile(ref, 98))

    res.overall_class = _class_string(res)
    res.class_code = _class_code(res)
    res.validation = "OK" if dec.ok else "FAIL"
    res.read_ok = dec.ok
    if res.elements:
        res.gs1_status = "warn" if res.gs1_warnings else "ok"
    else:
        res.gs1_status = "none"
    res.quality_ok = is_good(res)
    res.quality_status = ("good" if res.quality_ok
                          else ("bad" if res.read_ok else "unknown"))

    return res


def _parse_growth(s):
    """Parse '+19 мкм; +5,0%' into (um, pct)."""
    try:
        parts = s.replace(",", ".").replace(";", " ").split()
        um = float(parts[0])
        pct = float(parts[2].replace("%", ""))
        return um, pct
    except Exception:
        return 0.0, 0.0


def score_of(res):
    """Overall 0..100 score and gauge color."""
    if res.error or res.symbol is None:
        return 0, "#c62828"
    g = res.min_grade
    score = min(100, round(25 * g + 12))
    if res.validation != "OK":
        score = min(score, 35)
    color = "#2e7d32" if score >= 60 else ("#f9a825" if score >= 40 else "#c62828")
    return score, color


def is_good(res):
    """ГОДЕН requires a decoded code and grade above 1.5."""
    return res.validation == "OK" and not res.error and res.min_grade > 1.5


def hri_content(res):
    """GS1 HRI form: '(01)00012345600012(21)SER' (empty for plain codes)."""
    if not res.elements:
        return ""
    return "".join(f"({el.ai}){el.value}" for el in res.elements)


def plain_content(res):
    """Copy-friendly content: no AI parens, FS/RS separators stripped,
    but GS (\x1d) preserved — it is the standard GS1 field separator
    needed for correct parsing of variable-length AIs.

    Prefers the raw bytes (content_raw) with non-GS control chars stripped;
    falls back to the HRI text with parens removed.
    """
    if res.content_raw:
        return res.content_raw.replace("\x1c", "").replace("\x1e", "")
    if res.content:
        return res.content.replace("(", "").replace(")", "")
    return ""


def to_dict(res):
    """Serialize a Result into a plain JSON-friendly dict."""
    score, color = score_of(res)
    good = is_good(res)
    d = {
        "ok": res.ok and not res.error,
        "error": res.error,
        "content": res.content,
        "content_raw": res.content_raw,
        "content_plain": plain_content(res),
        "content_hri": hri_content(res),
        "symbology": res.symbology,
        "validation": res.validation,
        "read_ok": res.read_ok,
        "gs1_status": res.gs1_status,
        "quality_ok": res.quality_ok,
        "quality_status": res.quality_status,
        "good": good,
        "overall_class": res.overall_class,
        "class_code": res.class_code,
        "min_grade": res.min_grade,
        "score": score,
        "color": color,
        "um_per_px": res.um_per_px,
        "calibration_default": res.calibration_default,
        "calibration_note": calibration_note(res),
        "calibration_warning": calibration_warning(res),
        "module_px_x": res.module_px_x,
        "module_px_y": res.module_px_y,
        "x_dim_um": res.x_dim_um,
        "y_dim_um": res.y_dim_um,
        "aperture_um": res.aperture_um,
        "symbol_size": f"{res.symbol.rows}x{res.symbol.cols}" if res.symbol else None,
        "params": [
            {"name": p.name, "value": p.value, "grade": p.grade,
             "display": p.display, "scale": p.scale,
             "passed": p.passed, "level": p.level}
            for p in res.params
        ],
        "elements": [
            {"ai": el.ai, "name": el.display_name(),
             "label": el.display_label(), "value": el.value,
             "display_value": el.display_value(),
             "description": el.description}
            for el in res.elements
        ],
        "gs1_warnings": res.gs1_warnings,
        "regions": [
            {"label": r["label"], "severity": r["severity"],
             "poly": r["poly"].ravel().tolist()}
            for r in problem_regions(res)
        ],
        "corners": (res.corner_points.ravel().tolist()
                    if res.corner_points is not None else None),
    }
    return d


def _select_aperture(x_dim_um):
    """Smallest standard aperture >= X-dim/2, else 200."""
    target = x_dim_um / 2.0
    for a in STANDARD_APERTURES:
        if a >= target:
            return a
    return STANDARD_APERTURES[-1]


def _class_string(res):
    """Human-readable class line: '4,0 · 22×22 · 160 мкм'."""
    grade_str = fmt_ru(res.min_grade, 1)
    size = f"{res.symbol.rows}×{res.symbol.cols}"
    return f"{grade_str} · {size} · {int(res.aperture_um or 0)} мкм"


def _class_code(res):
    """Compact machine string for exports, e.g. '4.0/22/160'."""
    size = max(res.symbol.rows, res.symbol.cols)
    return f"{res.min_grade:.1f}/{size:02d}/{int(res.aperture_um or 0)}"


def _corners_ordered(corners):
    """Order 4 corners as tl, tr, br, bl (by angle from centroid)."""
    pts = np.asarray(corners, dtype=np.float32).reshape(4, 2)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    ordered = pts[np.argsort(ang)]
    # find the top-left by min(x+y)-ish; angle order starts at bottom-right
    # rotate so index 0 is the top-left corner.
    idx = int(np.argmin(ordered[:, 1] + ordered[:, 0] * 0.01))
    ordered = np.roll(ordered, -idx, axis=0)
    return ordered


def problem_regions(res):
    """Map failed parameters to image-space polygons for the heatmap.

    Returns a list of dicts: {label, severity, poly (Nx2)}.
    severity: 'critical' | 'warning' | 'minor'.
    """
    regions = []
    if res.corner_points is None:
        return regions
    tl, tr, br, bl = _corners_ordered(res.corner_points)

    def quad(p, q, r, s):
        return np.array([p, q, r, s], dtype=np.float32)

    def sub_quad(fx0, fy0, fx1, fy1):
        """Interpolate a sub-rect of the symbol by fractions."""
        p = tl + (tr - tl) * fx0 + (bl - tl) * fy0
        q = tl + (tr - tl) * fx1 + (bl - tl) * fy0
        r = tl + (tr - tl) * fx1 + (bl - tl) * fy1
        s = tl + (tr - tl) * fx0 + (bl - tl) * fy1
        return quad(p, q, r, s)

    grade_map = {}
    for p in res.params:
        grade_map[p.name] = p.grade

    def add(name, label, poly):
        g = grade_map.get(name, 4)
        if g < 3:
            sev = "critical" if g <= 1 else "warning"
            regions.append({"label": label, "severity": sev, "poly": poly})

    whole = quad(tl, tr, br, bl)
    add("Размерность печати X", "Размерность печати", whole)
    add("Осевая неоднородность", "Осевая неоднородность", whole)
    add("Левая часть шаблона \"L\"", "Левая часть шаблона L",
        sub_quad(0, 0.1, 0.18, 0.9))
    add("Нижняя часть шаблона \"L\"", "Нижняя часть шаблона L",
        sub_quad(0.1, 0.82, 0.9, 1.0))
    add("Последовательность тактовых модулей", "Тактовые модули",
        sub_quad(0.6, 0.0, 1.0, 0.4))
    add("Контраст символа", "Контраст", sub_quad(0.0, 0.0, 0.35, 0.35))
    add("Запас по коэффициенту отражения", "Отражение",
        sub_quad(0.0, 0.0, 0.35, 0.35))
    add("Неоднородность освещения", "Неравномерность освещения",
        sub_quad(0.0, 0.0, 1.0, 0.5))
    add("Запас коррекции ошибок", "Малый запас коррекции", whole)
    add("Свободная зона", "Малая свободная зона", whole)
    add("Декодирование", "Код не декодируется", whole)

    # dedupe identical polygons
    seen = set()
    out = []
    for reg in regions:
        key = (reg["label"], reg["poly"].tobytes())
        if key in seen:
            continue
        seen.add(key)
        out.append(reg)
    return out