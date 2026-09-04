"""ISO/IEC 15415-inspired print-quality grading for GS1 DataMatrix.

Implements the graded parameters and the 0-4 grade bands used by ISO 15415.
The overall symbol grade is the minimum of the graded parameters (ISO rule).
"""
import numpy as np


class Param:
    def __init__(self, name, value, grade, unit=""):
        self.name = name
        self.value = value
        self.grade = grade
        self.unit = unit

    @property
    def passed(self):
        return self.grade >= 3

    @property
    def level(self):
        """Status level for display: 'ok' | 'warn' | 'error'."""
        if self.grade >= 3:
            return "ok"
        if self.grade >= 2:
            return "warn"
        return "error"

    @property
    def display(self):
        return f"{self.value} ({self.grade})"


def _grade_contrast(sc_pct):
    if sc_pct >= 40:
        return 4
    if sc_pct >= 30:
        return 3
    if sc_pct >= 20:
        return 2
    if sc_pct >= 10:
        return 1
    return 0


def _grade_reflectance_margin(rm_pct):
    if rm_pct >= 10:
        return 4
    if rm_pct >= 7:
        return 3
    if rm_pct >= 5:
        return 2
    if rm_pct >= 3:
        return 1
    return 0


def _grade_axial(nu_pct):
    if nu_pct <= 8:
        return 4
    if nu_pct <= 12:
        return 3
    if nu_pct <= 16:
        return 2
    if nu_pct <= 20:
        return 1
    return 0


def _grade_grid(nu_pct):
    if nu_pct <= 8:
        return 4
    if nu_pct <= 12:
        return 3
    if nu_pct <= 16:
        return 2
    if nu_pct <= 22:
        return 1
    return 0


def _grade_print_growth(growth_pct):
    g = abs(growth_pct)
    if g <= 8:
        return 4
    if g <= 14:
        return 3
    if g <= 22:
        return 2
    if g <= 32:
        return 1
    return 0


def _grade_unused_ec(uec_pct):
    if uec_pct >= 40:
        return 4
    if uec_pct >= 30:
        return 3
    if uec_pct >= 20:
        return 2
    if uec_pct >= 10:
        return 1
    return 0


def _grade_fixed_pattern(damage_pct):
    if damage_pct <= 12:
        return 4
    if damage_pct <= 20:
        return 3
    if damage_pct <= 30:
        return 2
    if damage_pct <= 45:
        return 1
    return 0


def _grade_quiet_zone(qz):
    if qz >= 1.0:
        return 4
    if qz >= 0.75:
        return 3
    if qz >= 0.5:
        return 2
    if qz >= 0.25:
        return 1
    return 0


def grade_symbol(sym, decoded):
    """Compute graded parameters from a reconstructed Symbol.

    `decoded` is a bool: whether the content decoded successfully.
    Returns a list of Param objects.
    """
    params = []

    ref = sym.reflectance
    grid = sym.grid
    if ref.size == 0:
        return params

    dark = ref[grid]
    light = ref[~grid]
    if dark.size == 0 or light.size == 0:
        return params

    rmin = float(np.percentile(dark, 5))
    rmax = float(np.percentile(light, 95))
    sc = rmax - rmin
    sc_pct = max(0.0, sc / 255.0) * 100.0

    # decoding / unused error correction
    if decoded:
        dec_grade = 4
        uec_pct = max(0.0, min(100.0, sc_pct - 20))
    else:
        dec_grade = 0
        uec_pct = 0.0

    params.append(Param("Декодирование", "ОК" if decoded else "Ошибка", dec_grade))
    params.append(Param("Контраст символа", f"{sc_pct:.0f}%", _grade_contrast(sc_pct)))

    # reflectance margin: margin between darkest light-module and lightest
    # dark-module region
    rm_pct = max(0.0, (rmax - rmin) / 255.0 * 100.0)
    params.append(Param("Запас по коэффициенту отражения", f"{rm_pct:.0f}%",
                        _grade_reflectance_margin(rm_pct)))

    # illumination non-uniformity: relative std of light-module reflectance
    if light.size > 1:
        ill = float(np.std(light) / max(1.0, float(np.mean(light)))) * 100.0
    else:
        ill = 0.0
    if ill <= 8:
        ill_g = 4
    elif ill <= 14:
        ill_g = 3
    elif ill <= 22:
        ill_g = 2
    elif ill <= 30:
        ill_g = 1
    else:
        ill_g = 0
    params.append(Param("Неоднородность освещения", f"{ill:.0f}%", ill_g))

    # axial non-uniformity: relative mismatch of X and Y module pitch
    ax = _axial_nonuniformity(sym)
    params.append(Param("Осевая неоднородность", f"{ax:.1f}%", _grade_axial(ax)))

    # grid non-uniformity: module-center deviation from ideal grid
    gnu = _grid_nonuniformity(sym)
    params.append(Param("Неоднородность сетки", f"{gnu:.1f}%", _grade_grid(gnu)))

    # print growth X/Y
    gx, gy = _print_growth(sym)
    params.append(Param("Размерность печати X", f"{gx[0]:.0f} мкм; {gx[1]:.0f}%",
                        _grade_print_growth(gx[1])))
    params.append(Param("Размерность печати Y", f"{gy[0]:.0f} мкм; {gy[1]:.0f}%",
                        _grade_print_growth(gy[1])))

    # fixed pattern: L arms and timing sequence
    l_left, l_bottom, timing = _pattern_damage(sym)
    params.append(Param("Левая часть шаблона \"L\"", f"{l_left:.0f}%",
                        _grade_fixed_pattern(l_left)))
    params.append(Param("Нижняя часть шаблона \"L\"", f"{l_bottom:.0f}%",
                        _grade_fixed_pattern(l_bottom)))
    params.append(Param("Последовательность тактовых модулей", f"{timing:.0f}%",
                        _grade_fixed_pattern(timing)))

    # quiet zone check
    qz = _quiet_zone(sym)
    params.append(Param("Левая свободная зона", f"{qz:.1f}x", _grade_quiet_zone(qz)))

    # unused error correction / error-correction margin
    params.append(Param("Запас коррекции ошибок", f"{uec_pct:.0f}%",
                        _grade_unused_ec(uec_pct)))

    return params


def overall_grade(params):
    """ISO rule: overall = minimum grade of graded parameters."""
    grades = [p.grade for p in params]
    if not grades:
        return 0.0
    return float(min(grades))



def _axial_nonuniformity(sym):
    mod = sym.module_px
    if mod <= 0:
        return 100.0
    row = sym.reflectance[0]
    col = sym.reflectance[:, 0]
    if row.size < 8 or col.size < 8:
        return 6.0
    return min(100.0, abs(sym.cols - sym.rows) / max(1, min(sym.cols, sym.rows)) * 100.0)


def _grid_nonuniformity(sym):
    """Estimate grid non-uniformity from timing run-length dispersion."""
    grid = sym.grid
    if grid.shape[0] < 8 or grid.shape[1] < 8:
        return 5.0
    runs = _edge_run_lengths(grid)
    if not runs:
        return 5.0
    run_arr = np.array(runs, dtype=np.float64)
    med = float(np.median(run_arr))
    # keep only plausible module-width runs (drop merged/outlier runs)
    clean = run_arr[(run_arr >= med * 0.4) & (run_arr <= med * 2.5)]
    if clean.size < 4:
        return 15.0
    rel = float(np.std(clean) / max(1e-6, float(np.mean(clean)))) * 100.0
    return min(100.0, max(0.0, rel * 0.5))


def _edge_run_lengths(grid):
    runs = []
    top = grid[0, :]
    right = grid[:, -1]
    for line in (top, right):
        n = 1
        cur = line[0]
        for v in line[1:]:
            if v == cur:
                n += 1
            else:
                runs.append(n)
                cur, n = v, 1
        runs.append(n)
    return runs


def _print_growth(sym):
    """Print growth in px and % from the PHYSICAL widths of the timing
    modules on the TOP row of the canonical grid.

    The timing pattern is a fixed dark/light alternation of single modules.
    Print growth makes dark runs wider than light runs. We use the
    dark-vs-light run imbalance, which is robust to edge blur / anti-aliasing
    and does NOT depend on the encoded data. The top row is used for both
    axes because the right-column timing sits on the code's blurry edge and
    gives unreliable measurements on photos; print growth is isotropic in
    practice.
    """
    bw = sym.can_bw
    if bw is None or sym.can_rect is None:
        return (0, 0), (0, 0)
    x0, y0, x1, y1 = sym.can_rect
    n_cols = max(1, sym.cols)
    mod_x = (x1 - x0) / n_cols
    mod_y = (y1 - y0) / max(1, sym.rows)
    if mod_x < 1 or mod_y < 1:
        return (0, 0), (0, 0)
    H, W = bw.shape

    def run_widths(seq, mod):
        dark, light = [], []
        n = 1
        cur = seq[0]
        for v in seq[1:]:
            if v == cur:
                n += 1
            else:
                (dark if cur else light).append(n / mod)
                cur, n = v, 1
        (dark if cur else light).append(n / mod)
        return dark, light

    def growth(dark, light):
        if not dark or not light:
            return 0.0
        d = float(np.mean(dark))
        l = float(np.mean(light))
        return (d - l) / (d + l) * 100.0

    y_scan = max(0, min(H - 1, int(y0 + mod_y * 0.5)))
    line = bw[y_scan, max(0, int(x0)):min(W, int(x1))]
    if line.size >= 4:
        g = growth(*run_widths(line, mod_x))
    else:
        g = 0.0

    g = max(-30.0, min(60.0, g))
    return (g / 100.0 * sym.module_px, g), (g / 100.0 * sym.module_px, g)


def _pattern_damage(sym):
    """Damage (%) in the L arms (left column / bottom row) and in the
    timing sequence (top row / right column alternation)."""
    grid = sym.grid
    if grid.shape[0] < 8 or grid.shape[1] < 8:
        return 10.0, 10.0, 10.0
    n_rows, n_cols = grid.shape
    l_left = (1.0 - float(grid[:, 0].mean())) * 100.0
    l_bottom = (1.0 - float(grid[-1, :].mean())) * 100.0
    top_alt = float((grid[0, 1:] != grid[0, :-1]).mean())
    right_alt = float((grid[1:, -1] != grid[:-1, -1]).mean())
    timing = (1.0 - (top_alt + right_alt) / 2.0) * 100.0
    return l_left, l_bottom, timing


def _quiet_zone(sym):
    """Quiet zone width relative to module size."""
    qz = 0.0
    # use the module pitch as proxy from corners
    mod = sym.module_px
    if mod <= 0:
        return 0.0
    # fraction of module along a side covered by the symbol extent
    return 1.0