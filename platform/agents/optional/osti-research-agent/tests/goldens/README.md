# Golden parse corpus

A small, curated set of open-access OSTI PDFs used by `tests/test_goldens.py`
to exercise the real Docling parse ladder end to end.

This directory is intentionally empty in git. Fetch the corpus with:

```bash
uv run python scripts/download_goldens.py
```

`test_goldens.py` is marked `@pytest.mark.slow` (run with `pytest -m slow`, not
the default suite) and skips entirely when no `*.pdf` are present here, so a
clean checkout runs the fast suite without needing model weights or network.

**Follow-up (curation):** populate `GOLDEN_OSTI_IDS` in
`scripts/download_goldens.py` with ids that are reliably downloadable and
licensed for redistribution — one text-heavy, one table-heavy, one
figure-heavy, and one scanned/OCR paper — and record expected table/figure
counts so the test can assert on structure rather than just non-emptiness.
