"""Neural-network DataMatrix locator (corner regression).

Trained on shortery/dm-codes (ResNet18 + 4-corner head). Used as a fallback
locator when zxing and the classic L-pattern detection find nothing.
"""
import os

import cv2
import numpy as np
import torch
import torch.nn as nn
import torchvision
from PIL import Image

MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "models", "dm_corners.pth")

_model = None
_device = None
_input_size = 512


def _build():
    m = torchvision.models.resnet18()
    m.fc = nn.Linear(m.fc.in_features, 8)
    return m


def _load():
    global _model, _device, _input_size
    if _model is not None:
        return
    if not os.path.exists(MODEL_PATH):
        _model = False
        return
    ck = torch.load(MODEL_PATH, map_location="cpu")
    _input_size = ck.get("input_size", 512)
    _model = _build()
    _model.load_state_dict(ck["state_dict"])
    _model.eval()
    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    _model.to(_device)


def available():
    _load()
    return _model is not False


def predict(img):
    """Predict the 4 DataMatrix corners for an image.

    `img`: PIL image (RGB) or BGR numpy array. Returns a 4x2 float
    array in (x, y) image coordinates, or None if the model is unavailable.
    """
    _load()
    if not _model:
        return None
    if not isinstance(img, np.ndarray):
        rgb = np.asarray(img)  # PIL RGB
    elif img.ndim == 2:
        rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    else:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]

    pts = _forward(rgb)
    if pts is None:
        return None
    return pts


def _forward(rgb):
    """Single model pass over an RGB image -> 4x2 corners in image coords."""
    h, w = rgb.shape[:2]
    pil = Image.fromarray(rgb).resize((_input_size, _input_size), Image.LANCZOS)
    x = torch.from_numpy(np.asarray(pil, dtype=np.float32) / 255.0)
    x = x.permute(2, 0, 1).unsqueeze(0).to(_device)
    with torch.no_grad():
        out = _model(x).cpu().numpy().reshape(4, 2)  # normalized [0,1]
    out = out.clip(0, 1)
    return out * np.array([w, h], dtype=np.float32)


def predict_quad(img):
    """Return corners as a 4x2 array ordered for extract_grid."""
    pts = predict(img)
    if pts is None:
        return None
    return np.asarray(pts, dtype=np.float32).reshape(4, 2)