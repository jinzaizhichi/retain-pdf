# Source Cleanup

This package owns the boundary between render semantics and PDF source cleanup.

External callers should use this package instead of importing
`services.rendering.source.preparation.bbox_text_strip_*` directly.

## Contract

- `planner.py` turns translated render items and a source PDF into cleanup candidates.
- `executor.py` applies a cleanup request to a PDF and returns a cleanup result.
- `contracts.py` defines the request, options, and result objects.

The implementation owns bbox cleanup end to end. Old
`source.preparation.bbox_text_strip_*` modules have been removed; render-source
and prewarm callers should only depend on this package boundary.

## Boundary Rules

- `intents.py` defines the cleanup contract consumed by the planner.
- `planning/evidence.py` collects item facts from translated payloads.
- `planning/intent_classifier.py` maps evidence to cleanup intent. This is the
  only layer that should decide whether an item strips source text, protects
  source content, or does nothing.
- OCR block type, translation status, and formula protection are separate
  signals. Do not treat `block_kind=formula` as automatically protected source.
- Source text stripping must be driven by replacement intent. If an item has no
  translated overlay or other replacement, preserve the source instead of
  guessing from OCR labels or token patterns.
- Text items with embedded display/block math are preserved until the pipeline
  can split them into text and formula subregions. Inline math inside ordinary
  translated text remains deletable because the translated overlay replaces the
  whole text item.
- Business semantics belong in the planner layer.
- Geometry and formula guards belong below the planner.
- PDF content stream mutation belongs in the executor layer.
- `pdf/stream_engine.py` is the content stream coordinator.
- `pdf/stream_state.py` owns PDF graphics/text state transitions.
- `pdf/text_removal.py` owns text-show hit testing and protected-region checks.
- `pdf/xobject_ops.py` owns Form XObject clone-on-write recursion.
- Prewarm may ask this package for candidates, but should not build cleanup
  candidates by importing preparation modules directly.

## Performance Contract

- Physical pikepdf text stripping is an exact cleanup optimization, not a
  mandatory whole-book render prerequisite.
- Large overlay renders use Typst cover blocks for visual source hiding, so
  source prewarm skips whole-book physical stripping on that path.
- Form XObject recursion is enabled by default because some editable PDFs place
  inline formulas inside Form streams while surrounding text lives in the page
  stream. Skipping Forms leaves those formulas visible after source cleanup.
- Low-level `strip_bbox_text_rects_from_pdf_copy()` still supports
  `skip_form_xobject_pages=True` for explicit fast-path tests or emergency
  fallbacks.
