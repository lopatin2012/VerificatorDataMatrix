"""CLI entry point for the DataMatrix verifier.

Usage:
    python main.py --file path/to/image.jpg
    python main.py --dir samples
    python main.py --gui
"""
import argparse
import glob
import os
import sys

import cv2

from verifier import analyze
from version import VERSION


def print_report(res, path):
    print("=" * 60)
    print(f"Файл: {path}")
    if res.error:
        print("Код не найден:", res.error)
        return
    print("Статус:", res.overall_class, "| Валидация:", res.validation)
    print("-" * 60)
    print("Содержимое:", res.content if res.content else "(не декодировано)")
    print("Штрих-код:", res.symbology, f"({res.symbol.rows}x{res.symbol.cols})")
    print(f"X-размерность: {res.x_dim_um:.0f} мкм | Y: {res.y_dim_um:.0f} мкм | "
          f"Апертура: {res.aperture_um} мкм")
    print("-" * 60)
    for p in res.params:
        mark = "OK " if p.passed else "FAIL"
        print(f"  [{mark}] {p.name}: {p.display}")
    print("-" * 60)
    for el in res.elements:
        print(f"  {el.display_name():<8} = {el.value}")


def main():
    ap = argparse.ArgumentParser(description="DataMatrix verifier (ISO 15415)")
    ap.add_argument("--version", action="version",
                    version=f"DataMatrix Verifier {VERSION}")
    ap.add_argument("--file", help="analyze a single image file")
    ap.add_argument("--dir", help="analyze all images in a directory")
    ap.add_argument("--gui", action="store_true", help="launch the GUI")
    ap.add_argument("--web", action="store_true", help="launch the web service")
    ap.add_argument("--host", default="127.0.0.1", help="web service host")
    ap.add_argument("--port", type=int, default=8000, help="web service port")
    ap.add_argument("--um-per-px", type=float, default=10.0,
                    help="calibration, microns per pixel")
    args = ap.parse_args()

    if args.web:
        import webapp
        webapp.main(host=args.host, port=args.port)
        return

    if args.gui or (not args.file and not args.dir):
        from ui import main as gui_main
        gui_main()
        return

    paths = []
    if args.file:
        paths = [args.file]
    elif args.dir:
        paths = sorted(glob.glob(os.path.join(args.dir, "*")))
        paths = [p for p in paths if p.lower().endswith(
            (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"))]

    for path in paths:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            print("Не удалось прочитать:", path)
            continue
        res = analyze(img, um_per_px=args.um_per_px)
        print_report(res, path)


if __name__ == "__main__":
    sys.exit(main())