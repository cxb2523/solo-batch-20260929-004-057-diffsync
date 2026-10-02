# Example 07: Static Diff report

This example renders an example multi-level `Diff` (sites → devices → interfaces) as a
self-contained HTML page that shows:

- the distribution of element actions (`create` / `update` / `delete` / `no-change`),
- the nested children tree with the per-element attribute diffs,
- the versioned `Diff.dict()` payload actually used for the round trip through
  `Diff.from_dict()`.

## Run

```bash
python examples/07-diff-report/generate_report.py
```

Then open the generated `diff_report.html` in any browser. The page has no external
dependencies and is convenient for screen-recording before/after comparisons.
