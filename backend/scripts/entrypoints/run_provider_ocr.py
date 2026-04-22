"""Top-level OCR-only provider entry for local use.

This is the generic local entrypoint name for the OCR-only provider flow.
It stops after provider download/unpack plus document_schema normalization.
"""

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.mineru.ocr_pipeline import main


if __name__ == "__main__":
    main()
