"""Self-contained smoke tests for the verifier (no sample files needed).

Run with:  python main.py --selftest
"""
import cv2
import numpy as np
import zxingcpp

from gs1 import parse, validate
from verifier import analyze


def _module_map(text):
    bc = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.DataMatrix)
    img = zxingcpp.write_barcode_to_image(bc, scale=1, add_quiet_zones=False)
    return np.asarray(img)


def _render_solid(mod, cell=10, quiet=2):
    h, w = mod.shape
    canvas = np.full(((h + 2 * quiet) * cell, (w + 2 * quiet) * cell), 255,
                     np.uint8)
    big = cv2.resize((mod < 128).astype(np.uint8) * 255, (w * cell, h * cell),
                     interpolation=cv2.INTER_NEAREST)
    y0 = x0 = quiet * cell
    canvas[y0:y0 + h * cell, x0:x0 + w * cell] = 255 - big
    return canvas


def _render_dotted(mod, cell=12, quiet=2):
    r = max(2, int(cell * 0.32))
    h, w = mod.shape
    canvas = np.full(((h + 2 * quiet) * cell, (w + 2 * quiet) * cell), 255,
                     np.uint8)
    yy, xx = np.mgrid[0:2 * r + 1, 0:2 * r + 1]
    disk = (xx - r) ** 2 + (yy - r) ** 2 <= r * r
    for y in range(h):
        for x in range(w):
            if mod[y, x] < 128:
                cy = (y + quiet) * cell + cell // 2
                cx = (x + quiet) * cell + cell // 2
                canvas[cy - r:cy + r + 1, cx - r:cx + r + 1][disk] = 0
    return canvas


def _run_checks():
    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    # --- GS1 parsing / validation ---
    els = parse("(01)00012345600012(21)ABC123(93)EXT1")
    check("gs1: valid content has no warnings", validate(els) == [],
          str(validate(els)))
    bad = parse("(01)00012345600013(21)ABC")  # wrong GTIN check digit
    check("gs1: bad GTIN check digit flagged",
          any("GTIN" in w for w in validate(bad)), str(validate(bad)))
    unk = parse("(99)12345")
    check("gs1: unknown AI flagged",
          any("Неизвестный" in w for w in validate(unk)), str(validate(unk)))
    short = parse("(01)123")
    check("gs1: fixed-length mismatch flagged",
          any("14" in w for w in validate(short)), str(validate(short)))
    raw = parse(b"0100012345600012\x1d21SER\x1d93EXT")
    check("gs1: raw bytes with GS parse to same AIs",
          [e.ai for e in raw] == ["01", "21", "93"],
          str([(e.ai, e.value) for e in raw]))
    # A GS separator must end a variable field even when the value itself
    # contains digits that look like an AI.
    gs = parse(b"0100012345600012\x1d10LOT21X\x1d21SER")
    check("gs1: GS separator ends a variable-length field",
          [(e.ai, e.value) for e in gs]
          == [("01", "00012345600012"), ("10", "LOT21X"), ("21", "SER")],
          str([(e.ai, e.value) for e in gs]))
    check("gs1: HRI values keep their characters",
          [(e.ai, e.value) for e in parse("(01)00012345600012(10)LOT21X")]
          == [("01", "00012345600012"), ("10", "LOT21X")])
    # 4-digit measurement AI (310n = net weight) + fixed length.
    weight = parse(b"3103000123")
    check("gs1: pattern AI 310n parsed as fixed 6 digits",
          [(e.ai, e.value) for e in weight] == [("3103", "000123")]
          and validate(weight) == [],
          str([(e.ai, e.value) for e in weight]))
    bad_date = parse("(17)251332")
    check("gs1: impossible date flagged",
          any("некорректн" in w for w in validate(bad_date)),
          str(validate(bad_date)))
    ok_date = parse("(17)251231")
    check("gs1: valid date accepted",
          not any("некорректн" in w for w in validate(ok_date)),
          str(validate(ok_date)))

    # --- end-to-end decode: solid + dotted + inverted synthetic symbols ---
    mod = _module_map("HELLO-DM")
    cases = (
        ("solid", _render_solid(mod)),
        ("dotted dark-on-light", _render_dotted(mod)),
        ("dotted white-on-dark", 255 - _render_dotted(mod)),
    )
    for tag, img in cases:
        res = analyze(img)
        check(f"decode {tag}", res.content == "HELLO-DM",
              f"content={res.content!r} validation={res.validation} "
              f"error={res.error}")

    # --- geometry and grading regressions ---
    # 10 px modules at 10 um/px must report a 100 um X-dimension, not the
    # warp-space pitch (the old code reported ~550 um).
    res = analyze(_render_solid(mod, quiet=3))
    check("geometry: X/Y dimension is in source microns",
          res.x_dim_um is not None and abs(res.x_dim_um - 100) < 3
          and abs(res.y_dim_um - 100) < 3,
          f"x={res.x_dim_um} y={res.y_dim_um}")
    qz = next((p for p in res.params if p.name == "Свободная зона"), None)
    qz_value = None
    if qz is not None:
        try:
            qz_value = float(qz.value.rstrip("x"))
        except ValueError:
            qz_value = None
    check("geometry: quiet zone measured from the image",
          qz_value is not None and qz_value >= 2.5 and qz.grade >= 3,
          f"{qz.value if qz else None} (grade {qz.grade if qz else None})")
    # A code printed flush to the image border must not look like it has a
    # 1-module quiet zone (the old fallback returned 1.0 for everything).
    tight = analyze(_render_solid(mod, quiet=0))
    tight_qz = next((p for p in tight.params
                     if p.name == "Свободная зона"), None)
    check("geometry: missing quiet zone is reported",
          tight_qz is not None and tight_qz.grade <= 2,
          f"{tight_qz.value if tight_qz else None} "
          f"(grade {tight_qz.grade if tight_qz else None})")

    # Rectangular ECC200 symbols used to grade 0 because rows/cols were
    # compared as if they were the X/Y module pitch.
    rect = analyze(_render_solid(_module_map("A" * 20)))
    check("geometry: rectangular symbol decodes", rect.content == "A" * 20,
          f"content={rect.content!r} error={rect.error}")
    check("grade: rectangular aspect does not zero the grade",
          rect.min_grade is not None and rect.min_grade >= 3,
          f"grade={rect.min_grade}")
    check("geometry: rectangular symbol has square modules",
          rect.x_dim_um is not None and abs(rect.x_dim_um - 100) < 3
          and abs(rect.y_dim_um - 100) < 3,
          f"x={rect.x_dim_um} y={rect.y_dim_um}")

    return checks


def run():
    checks = _run_checks()
    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        line = f"[{'PASS' if ok else 'FAIL'}] {name}"
        if not ok and detail:
            line += f"  ({detail})"
        print(line)
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0
