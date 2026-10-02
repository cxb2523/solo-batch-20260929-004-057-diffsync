# Example 7 - Static HTML diff report

Builds a diff between two in-memory adapters (`SourceBackend` vs `DestBackend`)
and renders a self-contained static HTML report that can be opened in any
browser - useful for screen recordings and before/after comparisons.

The report contains:

- the action distribution (create/update/delete/no-change) as a bar chart,
- the full children tree of the `Diff`, with per-element action badges and
  attribute-level diffs,
- the raw `diff.dict()` serialization.

Run it from the repository root:

```shell
PYTHONPATH=. python examples/07-diff-report/main.py
```

Then open `examples/07-diff-report/diff_report.html` in a browser.
