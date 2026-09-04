"""Official PDF report generation for verification results."""
import os
import tempfile
import datetime

import cv2
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from version import VERSION

_FONTS = {"normal": None, "bold": None}


def _register_fonts():
    if _FONTS["normal"]:
        return
    normal = "Helvetica"
    bold = "Helvetica-Bold"
    for path, name in (("C:/Windows/Fonts/arial.ttf", "AppFont"),
                       ("C:/Windows/Fonts/times.ttf", "AppFontTimes"),
                       ("C:/Windows/Fonts/DejaVuSans.ttf", "AppFontDejaVu")):
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                normal = name
                break
            except Exception:
                continue
    for path, name in (("C:/Windows/Fonts/arialbd.ttf", "AppFontBold"),
                       ("C:/Windows/Fonts/DejaVuSans-Bold.ttf", "AppFontDejaVuBold")):
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                bold = name
                break
            except Exception:
                continue
    _FONTS["normal"] = normal
    _FONTS["bold"] = bold


def _annotated_image(frame_bgr, res):
    """Copy of the frame with a rectangle marking the located code.

    The rectangle is drawn OUTSIDE the symbol (margin), so it never overlaps
    the code modules.
    """
    img = frame_bgr.copy()
    if res.corner_points is not None:
        pts = res.corner_points.astype(int)
        x0, y0 = int(pts[:, 0].min()), int(pts[:, 1].min())
        x1, y1 = int(pts[:, 0].max()), int(pts[:, 1].max())
        m = max(10, int(0.08 * max(x1 - x0, y1 - y0)))
        cv2.rectangle(img, (x0 - m, y0 - m), (x1 + m, y1 + m), (20, 110, 200), 4)
        cv2.rectangle(img, (x0 - m, y0 - m), (x1 + m, y1 + m), (255, 255, 255), 1)
    return img


def _clean_para(s):
    """Make arbitrary text safe for a reportlab Paragraph.

    Escape XML metacharacters and drop control chars (the GS separator, etc.)
    that would otherwise break the paragraph parser or the PDF text stream.
    """
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "".join(ch if ch >= " " or ch in "\n\t\r" else " " for ch in s)


def build_pdf(res, frame_bgr, path):
    """Write an official verification report to `path`."""
    _register_fonts()
    F = _FONTS["normal"]
    FB = _FONTS["bold"]

    s_title = ParagraphStyle("title", fontName=FB, fontSize=16,
                             leading=20, textColor=colors.HexColor("#1a237e"))
    s_sub = ParagraphStyle("sub", fontName=F, fontSize=9, leading=12,
                           textColor=colors.HexColor("#78909c"))
    s_h = ParagraphStyle("h", fontName=FB, fontSize=12, leading=15,
                         textColor=colors.HexColor("#1a237e"),
                         spaceBefore=6, spaceAfter=3)
    s_body = ParagraphStyle("body", fontName=F, fontSize=10, leading=14)
    s_small = ParagraphStyle("small", fontName=F, fontSize=9, leading=12)

    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Отчет о верификации DataMatrix {VERSION}",
                            author="DataMatrix Verifier")

    now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    story = []

    title_table = Table(
        [[Paragraph("Отчет о верификации", s_title),
          Paragraph(f"DataMatrix Verifier v{VERSION}<br/>{now}", s_sub)]],
        colWidths=[120 * mm, 60 * mm])
    title_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.HexColor("#1a237e")),
    ]))
    story.append(title_table)
    story.append(Spacer(1, 4 * mm))

    # Info block
    cell = ParagraphStyle("infocell", fontName=FB, fontSize=9, leading=12)
    size_txt = f"{res.symbol.rows}x{res.symbol.cols}" if res.symbol else "—"
    xd = f"{res.x_dim_um:.0f}" if res.x_dim_um is not None else "—"
    yd = f"{res.y_dim_um:.0f}" if res.y_dim_um is not None else "—"
    ap = f"{res.aperture_um} мкм" if res.aperture_um is not None else "—"
    info = [
        ["Класс символа", res.overall_class or "—", "Штрих-код", "GS1 DataMatrix"],
        ["Содержимое",
         Paragraph(_clean_para(res.content or "(не декодировано)"), cell), "Размер символа",
         size_txt],
        ["X-размерность", xd, "Y-размерность", yd],
        ["Апертура", ap, "", ""],
    ]
    info_table = Table(info, colWidths=[38 * mm, 55 * mm, 38 * mm, 45 * mm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), F),
        ("FONTNAME", (1, 0), (1, -1), FB),
        ("FONTNAME", (2, 0), (2, -1), F),
        ("FONTNAME", (3, 0), (3, -1), FB),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f5f9")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#b0bec5")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd8dc")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 4 * mm))

    # Prominent validation verdict, centered above the image block
    val_ok = res.validation == "OK"
    val_style = ParagraphStyle(
        "valbig", fontName=FB, fontSize=20, leading=24, alignment=TA_CENTER,
        textColor=colors.HexColor("#2e7d32") if val_ok else colors.HexColor("#c62828"))
    story.append(Paragraph("Валидация: " + ("OK" if val_ok else "БРАК"), val_style))
    story.append(Spacer(1, 6 * mm))

    # Image with located code
    story.append(Paragraph("Расположение кода", s_h))
    img = _annotated_image(frame_bgr, res)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    cv2.imwrite(tmp.name, img)
    fw, fh = frame_bgr.shape[1], frame_bgr.shape[0]
    img_w = 160 * mm
    img_h = img_w * fh / fw
    max_h = 130 * mm
    if img_h > max_h:
        img_h = max_h
        img_w = img_h * fw / fh
    pil = Image(tmp.name, width=img_w, height=img_h)
    pil.hAlign = "CENTER"
    story.append(pil)
    story.append(Spacer(1, 4 * mm))

    # Parameters table
    story.append(Paragraph("Параметры по ISO 15415", s_h))
    header = [["Параметр", "Значение", "Статус"]]
    rows = []
    for p in res.params:
        status = "OK" if p.level == "ok" else ("Предупреждение" if p.level == "warn" else "Ошибка")
        rows.append([p.name, p.display, status])
    data = header + rows
    pt = Table(data, colWidths=[75 * mm, 55 * mm, 40 * mm],
               repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), FB),
        ("FONTNAME", (0, 1), (-1, -1), F),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#b0bec5")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd8dc")),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f3f5f9")))
    for i, p in enumerate(res.params, start=1):
        c = colors.HexColor("#2e7d32") if p.level == "ok" else (
            colors.HexColor("#b8860b") if p.level == "warn" else colors.HexColor("#c62828"))
        style.append(("TEXTCOLOR", (2, i), (2, i), c))
    pt.setStyle(TableStyle(style))
    story.append(pt)
    story.append(Spacer(1, 4 * mm))

    # GS1 data
    if res.elements:
        story.append(Paragraph("Данные GS1", s_h))
        cell = ParagraphStyle("cell", fontName=F, fontSize=8.5, leading=11)
        gdata = [["Элемент", "Значение", "Описание"]]
        for el in res.elements:
            gdata.append([Paragraph(_clean_para(el.display_name()), cell),
                          Paragraph(_clean_para(el.value), cell),
                          Paragraph(_clean_para(el.description), cell)])
        gt = Table(gdata, colWidths=[35 * mm, 80 * mm, 55 * mm], repeatRows=1)
        gt.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), FB),
            ("FONTNAME", (0, 1), (-1, -1), F),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#b0bec5")),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd8dc")),
        ]))
        story.append(gt)

    def footer(canvas, docobj):
        canvas.saveState()
        canvas.setFont(F, 8)
        canvas.setFillColor(colors.HexColor("#90a4ae"))
        canvas.drawString(16 * mm, 10 * mm,
                          f"DataMatrix Verifier v{VERSION} · {now}")
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm,
                               f"Стр. {docobj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    try:
        os.unlink(tmp.name)
    except OSError:
        pass
    return path