"""Entry point for the DataMatrix verifier.

Usage:
    python main.py                    # web service on 127.0.0.1:8010
    python main.py --file path/to/image.jpg
    python main.py --dir samples
    python main.py --dir samples --json
"""
import argparse
import glob
import json
import os
import sys

import cv2

import crpt
from verifier import (DEFAULT_UM_PER_PX, Result, analyze_all,
                      calibration_note, calibration_warning, hri_content,
                      imread_unicode, to_dict)
from version import VERSION

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")


def _positive_float(text):
    """argparse type: accept '8.5' and '8,5', reject non-positive values."""
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        raise argparse.ArgumentTypeError(f"не число: {text!r}")
    if value <= 0:
        raise argparse.ArgumentTypeError("калибровка должна быть больше нуля")
    return value


def print_report(res, path, index=None, total=None):
    print("=" * 60)
    title = f"Файл: {path}"
    if total is not None and total > 1:
        title += f"  [код {index}/{total}]"
    print(title)
    if res.error or res.symbol is None:
        print("Код не найден:", res.error or "символ не найден")
        return
    gs1 = {"ok": "OK",
           "warn": f"{len(res.gs1_warnings)} предупр.",
           "none": "—"}.get(res.gs1_status, "—")
    quality = ("ГОДЕН" if res.quality_ok
               else ("БРАК" if res.read_ok else "—"))
    print("Статус:", res.overall_class)
    print(f"Чтение: {'OK' if res.read_ok else 'ОШИБКА'} | GS1: {gs1} | "
          f"Качество: {quality}")
    print("-" * 60)
    print("Содержимое:", res.content if res.content else "(не декодировано)")
    hri = hri_content(res)
    if hri:
        print("HRI:", hri)
    print("Штрих-код:", res.symbology, f"({res.symbol.rows}x{res.symbol.cols})")
    print(f"X-размерность: {res.x_dim_um:.0f} мкм | Y: {res.y_dim_um:.0f} мкм | "
          f"Апертура: {res.aperture_um} мкм")
    print(calibration_note(res))
    warning = calibration_warning(res)
    if warning:
        print("  ВНИМАНИЕ:", warning)
    print("-" * 60)
    for p in res.params:
        mark = "OK  " if p.level == "ok" else ("WARN" if p.level == "warn" else "FAIL")
        print(f"  [{mark}] {p.name}: {p.display}")
    print("-" * 60)
    print("Шкала оценок 4/3/2/1:")
    for p in res.params:
        if p.scale:
            print(f"  {p.name}: {p.scale}")
    print("-" * 60)
    for el in res.elements:
        print(f"  {el.display_label()} = {el.display_value()}")
    for w in getattr(res, "gs1_warnings", []):
        print("  [WARN]", w)


def _crpt_public(info):
    """Drop the bulky raw upstream JSON from CLI/JSON output."""
    return {k: v for k, v in info.items() if k != "raw"}


def print_crpt(info):
    print("Честный знак (mobile.api.crpt.ru):")
    if info.get("error"):
        print("  Ошибка:", info["error"])
        return
    print("  Найден:", "да" if info.get("found") else "нет")
    print("  Проверка:", "пройдена" if info.get("check") else "не пройдена")
    fields = (
        ("Статус", "status_text"),
        ("Товар", "product_name"),
        ("Категория", "category_text"),
        ("Производитель", "producer"),
        ("Владелец", "owner"),
        ("ИНН владельца", "owner_inn"),
        ("Бренд", "brand"),
        ("Страна", "country"),
        ("GTIN", "gtin"),
        ("Серийный номер", "serial"),
        ("Срок годности", "expiry"),
        ("Дата производства", "produced"),
        ("Сообщение", "message"),
    )
    for label, key in fields:
        value = info.get(key)
        if value:
            print(f"  {label}: {value}")
    if info.get("warning_text"):
        print("  Предупреждение:", info["warning_text"])
    attrs = info.get("attributes") or {}
    for name, value in attrs.items():
        print(f"  {name}: {value}")


def _error_result(msg):
    res = Result()
    res.error = msg
    return res


def run_files(paths, um_per_px, as_json=False, crpt_lookup=False):
    """Analyze every image; returns 0 if each decoded at least one code."""
    failures = 0
    payload = []
    crpt_infos = {}
    for path in paths:
        img = imread_unicode(path, cv2.IMREAD_COLOR)
        if img is None:
            if as_json:
                payload.append({"file": path,
                                "error": "Не удалось прочитать изображение",
                                "results": []})
            else:
                print("Не удалось прочитать:", path)
            failures += 1
            continue

        try:
            results = analyze_all(img, um_per_px=um_per_px)
        except Exception as exc:  # keep batch runs going on one bad image
            if as_json:
                payload.append({"file": path,
                                "error": f"Ошибка анализа: {exc}",
                                "results": []})
            else:
                print(f"Ошибка анализа {path}: {exc}")
            failures += 1
            continue

        if crpt_lookup:
            for res in results:
                code = res.content_raw or ""
                if not code or code in crpt_infos:
                    continue
                try:
                    info = crpt.lookup(code)
                except crpt.CrptError as exc:
                    info = {"ok": False, "error": str(exc)}
                crpt_infos[code] = _crpt_public(info)

        if as_json:
            items = []
            for res in results:
                d = to_dict(res)
                info = crpt_infos.get(res.content_raw or "")
                if info is not None:
                    d["crpt"] = info
                items.append(d)
            payload.append({"file": path, "results": items})
            # `ok` is also true for a located-but-undecoded symbol; the exit
            # code must reflect an actual successful read.
            if not any(d["validation"] == "OK" for d in items):
                failures += 1
        elif results:
            for i, res in enumerate(results, start=1):
                print_report(res, path, i, len(results))
                info = crpt_infos.get(res.content_raw or "")
                if info is not None:
                    print_crpt(info)
            if not any(r.validation == "OK" for r in results):
                failures += 1
        else:
            print_report(_error_result("Код не найден"), path)
            failures += 1

    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description="DataMatrix verifier (ISO 15415)")
    ap.add_argument("--version", action="version",
                    version=f"DataMatrix Verifier {VERSION}")
    ap.add_argument("--file", help="analyze a single image file")
    ap.add_argument("--dir", help="analyze all images in a directory")
    ap.add_argument("--web", action="store_true",
                    help="launch the web service (default without "
                         "--file/--dir)")
    ap.add_argument("--selftest", action="store_true",
                    help="run built-in smoke tests and exit")
    ap.add_argument("--json", action="store_true",
                    help="print machine-readable JSON (with --file/--dir)")
    ap.add_argument("--crpt", action="store_true",
                    help="look up product info in Chestny Znak "
                         "(network request, opt-in)")
    ap.add_argument("--host", default="127.0.0.1", help="web service host")
    ap.add_argument("--port", type=int, default=8010, help="web service port")
    ap.add_argument("--um-per-px", type=_positive_float, default=None,
                    help=f"calibration, microns per pixel "
                         f"(default: {DEFAULT_UM_PER_PX:g}, marked as approximate)")
    args = ap.parse_args()

    if args.json and not (args.file or args.dir):
        ap.error("--json requires --file or --dir")
    if args.crpt and (args.web or not (args.file or args.dir)):
        ap.error("--crpt is only for the CLI (--file/--dir)")

    if args.selftest:
        import selftest
        return selftest.run()

    if args.web or (not args.file and not args.dir):
        import webapp
        webapp.main(host=args.host, port=args.port)
        return 0

    paths = []
    if args.file:
        paths = [args.file]
    elif args.dir:
        paths = sorted(glob.glob(os.path.join(args.dir, "*")))
        paths = [p for p in paths if p.lower().endswith(IMAGE_EXTENSIONS)]

    if not paths:
        print("Изображения не найдены.", file=sys.stderr)
        return 1

    return run_files(paths, args.um_per_px, as_json=args.json,
                     crpt_lookup=args.crpt)


if __name__ == "__main__":
    sys.exit(main())
