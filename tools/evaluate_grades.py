"""Evaluate grade accuracy against a labeled folder (e.g. samples/G0..G4).

Labels are taken from file names:
    G0_*.jpg ... G4_*.jpg   -> expected grade 0..4
    G_ERROR_*.jpg           -> expected "not good" (unreadable or fail)

Usage:
    .venv\\Scripts\\python.exe tools\\evaluate_grades.py --dir samples
    .venv\\Scripts\\python.exe tools\\evaluate_grades.py --dir samples --csv grades.csv
    .venv\\Scripts\\python.exe tools\\evaluate_grades.py --dir samples --strict

This is a local calibration aid: it never calls the network and does not change
the application. Run it against the owner's labeled sample set before tuning
any thresholds in core/grade.py.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from verifier import analyze_all, fmt_ru, imread_unicode, is_good  # noqa: E402

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")
GRADE_LABELS = (0, 1, 2, 3, 4)


def label_of(path):
    name = path.stem
    if re.match(r"G[_-]?ERROR", name, re.I):
        return "ERROR"
    match = re.match(r"G(\d)", name, re.I)
    if match:
        value = int(match.group(1))
        return value if value in GRADE_LABELS else None
    return None


def grade_int(value):
    if value is None:
        return None
    return max(0, min(4, int(float(value) + 0.5)))


def find_images(folder):
    return sorted(p for p in folder.rglob("*")
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)


def analyze_one(path, um_per_px):
    img = imread_unicode(str(path), cv2.IMREAD_COLOR)
    if img is None:
        return {"file": str(path), "grade": None, "rounded": None,
                "class": None, "good": False, "validation": "FAIL",
                "codes": 0, "error": "не удалось прочитать"}
    try:
        results = analyze_all(img, um_per_px=um_per_px)
    except Exception as exc:  # keep the batch going
        return {"file": str(path), "grade": None, "rounded": None,
                "class": None, "good": False, "validation": "FAIL",
                "codes": 0, "error": f"ошибка анализа: {exc}"}
    if not results:
        return {"file": str(path), "grade": None, "rounded": None,
                "class": None, "good": False, "validation": "FAIL",
                "codes": 0, "error": "код не найден"}
    res = results[0]
    return {
        "file": str(path),
        "grade": res.min_grade,
        "rounded": grade_int(res.min_grade),
        "class": res.overall_class,
        "good": is_good(res),
        "validation": res.validation,
        "codes": len(results),
        "error": res.error,
    }


def confusion(rows):
    matrix = {ref: {got: 0 for got in (*GRADE_LABELS, None)}
              for ref in GRADE_LABELS}
    for row in rows:
        ref = row["label"]
        if isinstance(ref, int):
            matrix[ref][row["rounded"]] += 1
    return matrix


def summarize(rows):
    numeric = [r for r in rows if isinstance(r["label"], int)]
    errors = [r for r in rows if r["label"] == "ERROR"]
    compared = [r for r in numeric if r["rounded"] is not None]
    exact = [r for r in compared if r["rounded"] == r["label"]]
    near = [r for r in compared
            if r["rounded"] is not None and abs(r["rounded"] - r["label"]) <= 1]
    abs_err = [abs(r["rounded"] - r["label"]) for r in compared]
    return {
        "total": len(rows),
        "numeric": len(numeric),
        "errors": len(errors),
        "unread": sum(1 for r in rows if r["rounded"] is None),
        "compared": len(compared),
        "exact": len(exact),
        "near": len(near),
        "mean_abs": (sum(abs_err) / len(abs_err)) if abs_err else 0.0,
        "error_ok": sum(1 for r in errors if not r["good"]),
        "error_bad": sum(1 for r in errors if r["good"]),
        "confusion": confusion(rows),
    }


def print_report(rows, summary, verbose=False):
    print(f"Размеченных файлов: {summary['total']} "
          f"(числовых {summary['numeric']}, ERROR {summary['errors']})")
    print(f"Без кода/не прочитано: {summary['unread']}")
    if summary["compared"]:
        print(f"Совпадение: {summary['exact']}/{summary['compared']} "
              f"({100.0 * summary['exact'] / summary['compared']:.0f}%)")
        print(f"В пределах ±1: {summary['near']}/{summary['compared']}")
        print(f"Средняя |ошибка|: {fmt_ru(summary['mean_abs'], 2)}")
    if summary["errors"]:
        print(f"ERROR: {summary['errors']} (БРАК {summary['error_ok']}, "
              f"ошибочно ГОДЕН {summary['error_bad']})")

    print()
    print("Матрица: строки — эталон, столбцы — наш округлённый грейд")
    header = "       " + " ".join(f"{g:>4}" for g in GRADE_LABELS) + "  нет"
    print(header)
    for ref in GRADE_LABELS:
        row = summary["confusion"][ref]
        cells = " ".join(f"{row[g]:>4}" for g in GRADE_LABELS)
        print(f"  {ref}    {cells} {row[None]:>4}")

    mismatches = [r for r in rows
                  if (isinstance(r["label"], int)
                      and r["rounded"] != r["label"])
                  or (r["label"] == "ERROR" and r["good"])]
    if mismatches:
        print()
        print("Несовпадения:")
        for row in mismatches:
            got = ("нет" if row["rounded"] is None
                   else f"{fmt_ru(row['grade'], 1)} → {row['rounded']}")
            print(f"  {row['file']}: эталон {row['label']}, наш {got}"
                  f" — {row['class'] or row['error'] or ''}")
    if verbose:
        print()
        print("Все файлы:")
        for row in rows:
            got = ("нет" if row["rounded"] is None
                   else f"{fmt_ru(row['grade'], 1)} ({row['rounded']})")
            print(f"  {row['file']}: эталон {row['label']}, наш {got}, "
                  f"{'ГОДЕН' if row['good'] else 'БРАК'}")


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Файл", "Эталон", "Грейд", "Округлённый",
                         "Класс", "ГОДЕН", "Валидация", "Кодов", "Ошибка"])
        for row in rows:
            writer.writerow([
                row["file"], row["label"],
                "" if row["grade"] is None else fmt_ru(row["grade"], 2),
                "" if row["rounded"] is None else row["rounded"],
                row["class"] or "", "да" if row["good"] else "нет",
                row["validation"], row["codes"], row["error"] or "",
            ])


def write_json(path, rows, summary):
    data = {"rows": rows, "summary": summary}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser(
        description="Compare verifier grades with G0..G4 file labels")
    ap.add_argument("--dir", default="samples",
                    help="folder with labeled images (default: samples)")
    ap.add_argument("--um-per-px", type=float, default=None,
                    help="calibration; default = 10 um/px marked approximate")
    ap.add_argument("--csv", help="write per-file CSV")
    ap.add_argument("--json", help="write per-file JSON")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any mismatch or ERROR accepted as good")
    ap.add_argument("--verbose", action="store_true",
                    help="print every file, not only mismatches")
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f"Папка не найдена: {folder}", file=sys.stderr)
        return 2
    images = find_images(folder)
    labeled = [(p, label_of(p)) for p in images]
    labeled = [(p, label) for p, label in labeled if label is not None]
    if not labeled:
        print(f"В {folder} нет файлов с метками G0..G4 / G_ERROR",
              file=sys.stderr)
        return 2

    rows = []
    for path, label in labeled:
        row = analyze_one(path, args.um_per_px)
        row["label"] = label
        rows.append(row)

    summary = summarize(rows)
    print_report(rows, summary, verbose=args.verbose)
    if args.csv:
        write_csv(args.csv, rows)
        print(f"\nCSV: {args.csv}")
    if args.json:
        write_json(args.json, rows, summary)
        print(f"JSON: {args.json}")

    if args.strict:
        mismatches = sum(
            1 for r in rows
            if (isinstance(r["label"], int) and r["rounded"] != r["label"])
            or (r["label"] == "ERROR" and r["good"]))
        return 1 if mismatches else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
