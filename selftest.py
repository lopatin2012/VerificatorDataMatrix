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
