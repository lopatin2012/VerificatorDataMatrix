"""Image visualization helpers shared by the desktop and web UIs."""
import cv2
import numpy as np
from PIL import Image, ImageDraw

from verifier import problem_regions

SEV_COLORS = {
    "critical": "#e53935",
    "warning": "#fb8c00",
    "minor": "#fdd835",
}


def overlay_image(bgr, res, channel="color", focus_index=None):
    """Build an annotated RGB image: symbol outline + problem-zone heatmap.

    Returns a PIL RGB image (original resolution).
    """
    if channel == "gray":
        g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        arr = cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)
    elif channel == "ir":
        g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        g = cv2.equalizeHist(g)
        arr = cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)
    else:
        arr = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    img = Image.fromarray(arr).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    if res is not None and res.corner_points is not None:
        pts = res.corner_points.astype(np.float32)
        ring = [(float(x), float(y)) for x, y in pts] + [tuple(pts[0])]
        d.line(ring, fill=(46, 125, 50, 255), width=max(3, img.width // 400))

    regions = problem_regions(res) if res is not None else []
    for i, reg in enumerate(regions):
        color = SEV_COLORS[reg["severity"]]
        rgb = tuple(int(color.lstrip("#")[k:k + 2], 16) for k in (0, 2, 4))
        poly = [(float(x), float(y)) for x, y in reg["poly"]]
        alpha = 230 if focus_index == i else 150
        if focus_index == i:
            d.line(poly + [poly[0]], fill=rgb + (255,), width=4)
        d.polygon(poly, fill=rgb + (alpha,))
        d.line(poly + [poly[0]], fill=rgb + (220,), width=2)

    return Image.alpha_composite(img, overlay).convert("RGB")