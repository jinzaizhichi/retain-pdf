"""Top-level one-command MinerU entry.

This thin wrapper keeps the recommended CLI at `scripts/` while
reusing the stable implementation in `integrations/mineru/mineru_pipeline.py`.
"""

from integrations.mineru.mineru_pipeline import main


if __name__ == "__main__":
    main()
