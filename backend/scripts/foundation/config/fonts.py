import os
from pathlib import Path


DEFAULT_FONT_PATH = Path(
    os.environ.get("RETAIN_PDF_FONT_PATH", "").strip()
    or "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
)
DEFAULT_FONT_SIZE = 11.4
MIN_FONT_SIZE = 8.5
TYPST_DEFAULT_FONT_FAMILY = os.environ.get("RETAIN_PDF_TYPST_FONT_FAMILY", "").strip() or "Source Han Serif SC"
