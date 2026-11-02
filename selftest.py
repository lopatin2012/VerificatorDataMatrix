"""Self-contained smoke tests for the verifier (no sample files needed).

Run with:  python main.py --selftest
"""
import cv2
import numpy as np
import zxingcpp

import crpt
from core.grade import _grade_contrast
from gs1 import is_gs1, parse, validate
from verifier import (_parse_growth, analyze, calibration_note, hri_content,
                      to_dict)


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
    check("gs1: date is human-readable",
          parse("(17)251231")[0].display_value() == "31.12.2025",
          parse("(17)251231")[0].display_value())
    check("gs1: DD=00 renders the last day of the month",
          parse("(17)251200")[0].display_value() == "31.12.2025",
          parse("(17)251200")[0].display_value())
    check("gs1: date-time AI 7003 is human-readable",
          parse("(7003)2512312359")[0].display_value()
          == "31.12.2025 23:59",
          parse("(7003)2512312359")[0].display_value())
    expired = validate(parse("(17)200101"))
    check("gs1: expired date is warned", any("истёк" in w for w in expired),
          str(expired))
    future = validate(parse("(17)491231"))
    check("gs1: future date is not marked expired",
          not any("истёк" in w for w in future), str(future))
    check("gs1: detection accepts GS1 and rejects plain data",
          is_gs1(b"0100012345600012\x1d21SER",
                 parse(b"0100012345600012\x1d21SER"))
          and not is_gs1(b"HELLO-DM", parse(b"HELLO-DM")))

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
            qz_value = float(qz.value.split()[0].replace(",", "."))
        except (ValueError, IndexError):
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

    # --- calibration and report formatting ---
    check("calibration: default 10 um/px is flagged",
          res.calibration_default and res.um_per_px == 10.0,
          f"{res.um_per_px} default={res.calibration_default}")
    custom = analyze(_render_solid(mod, quiet=3), um_per_px=20.0)
    check("calibration: explicit value changes the scale",
          not custom.calibration_default and custom.um_per_px == 20.0
          and abs(custom.x_dim_um - 2 * res.x_dim_um) < 2,
          f"{custom.um_per_px} default={custom.calibration_default} "
          f"x={custom.x_dim_um} vs {res.x_dim_um}")
    check("calibration: note distinguishes default and custom",
          "по умолчанию" in calibration_note(res)
          and "задана" in calibration_note(custom),
          f"{calibration_note(res)} / {calibration_note(custom)}")
    check("report: class line is human-readable",
          "×" in res.overall_class and "мкм" in res.overall_class
          and "/" not in res.overall_class,
          res.overall_class)
    axial = next((p for p in res.params
                  if p.name == "Осевая неоднородность"), None)
    check("report: parameter values use a decimal comma",
          axial is not None and "," in axial.value, axial.value if axial else "")
    growth = next((p for p in res.params
                   if p.name == "Размерность печати X"), None)
    check("report: print growth is signed and keeps a unit",
          growth is not None and growth.value[0] in "+-"
          and "мкм" in growth.value, growth.value if growth else "")
    check("report: growth parser accepts a comma",
          _parse_growth("+1,8 мкм; +2,0%") == (1.8, 2.0))
    uec = next((p for p in res.params if p.name == "Запас коррекции ошибок"),
               None)
    check("grade: zxing UEC is used for unused error correction",
          uec is not None and uec.value == "100%" and uec.grade == 4,
          f"{uec.value if uec else None} ({uec.grade if uec else None})")
    check("grade: contrast thresholds follow the ISO-oriented scale",
          [_grade_contrast(v) for v in (70, 55, 40, 20, 19, 62)]
          == [4, 3, 2, 1, 0, 3])
    illum = next((p for p in res.params
                  if p.name == "Неоднородность освещения"), None)
    check("grade: illumination uses a robust spread",
          illum is not None and illum.grade == 4
          and float(illum.value.rstrip("%").replace(",", ".")) <= 8.0,
          f"{illum.value if illum else None} "
          f"({illum.grade if illum else None})")

    # --- separated read / GS1 / quality statuses ---
    check("status: plain DataMatrix is not reported as GS1",
          res.gs1_status == "none" and not res.gs1_warnings
          and res.symbology == "DataMatrix",
          f"{res.symbology} {res.gs1_status} {res.gs1_warnings}")
    check("status: plain DataMatrix has no HRI",
          hri_content(res) == "", hri_content(res))
    check("status: read and quality flags are explicit",
          res.read_ok and res.quality_ok and res.quality_status == "good",
          f"read={res.read_ok} quality={res.quality_ok} "
          f"status={res.quality_status}")
    gs1_res = analyze(_render_solid(
        _module_map("0100012345600012\x1d17251332"), quiet=3))
    check("status: GS1 warnings are reported separately",
          gs1_res.gs1_status == "warn" and gs1_res.gs1_warnings
          and gs1_res.symbology == "GS1 DataMatrix",
          f"{gs1_res.symbology} {gs1_res.gs1_status} {gs1_res.gs1_warnings}")
    check("gs1: HRI is generated for a GS1 result",
          hri_content(gs1_res).startswith("(01)")
          and "(17)" in hri_content(gs1_res), hri_content(gs1_res))
    payload = to_dict(res)
    check("report: JSON carries statuses and threshold scales",
          payload["read_ok"] and payload["quality_ok"]
          and payload["gs1_status"] == "none"
          and bool(payload["params"][1]["scale"]),
          f"{payload['gs1_status']} {payload['params'][1].get('scale')}")
    gs1_payload = to_dict(gs1_res)
    check("report: JSON carries HRI and AI display values",
          gs1_payload["content_hri"].startswith("(01)")
          and gs1_payload["elements"][0]["ai"] == "01"
          and gs1_payload["elements"][0]["display_value"]
          == "00012345600012"
          and payload["content_hri"] == "",
          str(gs1_payload["elements"][:1]))

    # --- Chestny Znak response normalization (no network) ---
    cz_raw = {
        "codeFounded": True, "checkResult": False, "category": "beer",
        "status": "wrong", "warning": "not_verified",
        "codeResolveData": {
            "gtin": "04605622007626", "cis": "5Gf>n9p",
            "verified": False, "valid": True, "isBlocked": False,
            "ais": {"gtin": "04605622007626", "serial": "5Gf>n9p"},
            "message": "Code is invalid (cryptoEnd missing or incorrect)",
        },
        "beerData": {
            "productName": "Пиво светлое",
            "producerName": "АО \"Завод\"",
            "status": "RETIRED",
            "expirationDate": "2024-04-19T00:00:00Z",
            "producedDate": 1709337600000,
        },
        "catalogData": [{"good_attrs": [
            {"attr_name": "Страна производства", "attr_value": "Россия"},
            {"attr_name": "Тип упаковки", "attr_value": "КЕГ"},
        ]}],
    }
    cz = crpt.parse_response(cz_raw)
    check("crpt: response normalized",
          cz["found"] and not cz["check"] and not cz["verified"]
          and cz["product_name"] == "Пиво светлое"
          and cz["producer"] == 'АО "Завод"'
          and cz["status_text"] == "Выведен из оборота"
          and cz["country"] == "Россия",
          f"{cz['product_name']} / {cz['status_text']} / {cz['country']}")
    check("crpt: dates and warning are human-readable",
          cz["expiry"] == "19.04.2024" and cz["produced"] == "02.03.2024"
          and "криптохвост" in (cz["warning_text"] or ""),
          f"{cz['expiry']} / {cz['produced']} / {cz['warning_text']}")
    cz_missing = crpt.parse_response({
        "codeFounded": False, "checkResult": False,
        "status": "not_found", "warning": "not_found",
    })
    check("crpt: not-found response stays non-fatal",
          not cz_missing["found"] and cz_missing["status_text"]
          == "Не найден", str(cz_missing["warning_text"]))

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
