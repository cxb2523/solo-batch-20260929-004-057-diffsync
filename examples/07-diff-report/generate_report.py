#!/usr/bin/env python3
"""Generate a self-contained static HTML report of an example Diff.

Run::

    python examples/07-diff-report/generate_report.py

This builds a representative multi-level Diff (sites -> devices -> interfaces), serializes it
through ``Diff.dict()`` / ``Diff.from_dict()`` to prove the data shown is the round-trippable
payload, and writes ``diff_report.html`` next to this script. Open that file in any browser;
it has no external dependencies, which makes it convenient for screen recording / before-after
comparisons of how a Diff is normalized and serialized.
"""

import html
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from diffsync.diff import Diff, DiffElement

REPORT_PATH = Path(__file__).resolve().parent / "diff_report.html"

ACTION_COLORS = {
    "create": "#2e7d32",
    "update": "#ef6c00",
    "delete": "#c62828",
    "no-change": "#616161",
}


def build_example_diff():
    """Construct a non-trivial Diff exercising create/update/delete and nested children."""
    diff = Diff()

    # Site "nyc" itself is unchanged, but contains changed devices -> action None container.
    nyc = DiffElement("site", "nyc", {"name": "nyc"}, source_name="backend-a", dest_name="backend-b")

    # device nyc-spine1: updated role, with an updated and a newly created interface.
    spine1 = DiffElement(
        "device", "nyc-spine1", {"name": "nyc-spine1"}, source_name="backend-a", dest_name="backend-b"
    )
    spine1.add_attrs(source={"role": "spine"}, dest={"role": "leaf"})

    eth0 = DiffElement(
        "interface", "eth0", {"device_name": "nyc-spine1", "name": "eth0"},
        source_name="backend-a", dest_name="backend-b",
    )
    eth0.add_attrs(
        source={"interface_type": "ethernet", "description": "uplink to core"},
        dest={"interface_type": "ethernet", "description": "old uplink"},
    )
    eth1 = DiffElement(
        "interface", "eth1", {"device_name": "nyc-spine1", "name": "eth1"},
        source_name="backend-a", dest_name="backend-b",
    )
    eth1.add_attrs(source={"interface_type": "ethernet", "description": "new server port"})
    spine1.add_child(eth0)
    spine1.add_child(eth1)

    # device nyc-spine2: only present in the source -> create.
    spine2 = DiffElement(
        "device", "nyc-spine2", {"name": "nyc-spine2"}, source_name="backend-a", dest_name="backend-b"
    )
    spine2.add_attrs(source={"role": "spine"})
    removed_intf = DiffElement(
        "interface", "eth9", {"device_name": "nyc-spine2", "name": "eth9"},
        source_name="backend-a", dest_name="backend-b",
    )
    removed_intf.add_attrs(source={"interface_type": "ethernet", "description": "decommissioned port"})
    spine2.add_child(removed_intf)

    nyc.add_child(spine1)
    nyc.add_child(spine2)
    diff.add(nyc)

    # Site "rdu" only exists in the destination -> delete, with an unchanged device underneath
    # (action None leaf, excluded from the serialized payload).
    rdu = DiffElement("site", "rdu", {"name": "rdu"}, source_name="backend-a", dest_name="backend-b")
    rdu.add_attrs(dest={})
    unchanged_device = DiffElement(
        "device", "rdu-spine1", {"name": "rdu-spine1"}, source_name="backend-a", dest_name="backend-b"
    )
    unchanged_device.add_attrs(source={"role": "spine"}, dest={"role": "spine"})
    rdu.add_child(unchanged_device)
    diff.add(rdu)

    # A standalone no-change element that should be omitted from the report payload entirely.
    place = DiffElement("place", "Statue of Liberty", {"name": "Statue of Liberty"},
                        source_name="backend-a", dest_name="backend-b")
    place.add_attrs(source={"visited": True}, dest={"visited": True})
    diff.add(place)

    diff.models_processed = 12
    return diff


def collect_action_counts(element, counter):
    """Count the effective action of an element (None -> no-change) and recurse into children."""
    counter[element.action or "no-change"] += 1
    for child in element.get_children():
        collect_action_counts(child, counter)


def render_tree(element):
    """Render one DiffElement (and its children) as nested HTML <ul>/<li> markup."""
    action = element.action or "no-change"
    color = ACTION_COLORS[action]
    label = html.escape(f'{element.type}: {element.name}')
    diffs = element.get_attrs_diffs()
    detail_bits = []
    if "+" in diffs:
        detail_bits.append(f'+ {html.escape(json.dumps(diffs["+"], ensure_ascii=False))}')
    if "-" in diffs:
        detail_bits.append(f'- {html.escape(json.dumps(diffs["-"], ensure_ascii=False))}')
    detail = f' <span class="attrs">{" &nbsp;|&nbsp; ".join(detail_bits)}</span>' if detail_bits else ""
    children = list(element.get_children())
    inner = ""
    if children:
        inner = "<ul>" + "".join(render_tree(child) for child in children) + "</ul>"
    return (
        f'<li><span class="badge" style="background:{color}">{html.escape(action)}</span>'
        f'<span class="node">{label}</span>{detail}{inner}</li>'
    )


def render_html(diff, payload):
    """Render the full report HTML string."""
    counter = Counter()
    for child in diff.get_children():
        collect_action_counts(child, counter)
    for action in ("create", "update", "delete", "no-change"):
        counter.setdefault(action, 0)

    total = sum(counter.values())
    bars = []
    for action in ("create", "update", "delete", "no-change"):
        count = counter[action]
        pct = (100.0 * count / total) if total else 0
        bars.append(
            f"""
        <div class="bar-row">
          <div class="bar-label">{action}</div>
          <div class="bar-track">
            <div class="bar-fill" style="width:{pct:.1f}%;background:{ACTION_COLORS[action]}"></div>
          </div>
          <div class="bar-count">{count}</div>
        </div>"""
        )

    tree_items = "".join(render_tree(child) for child in diff.get_children())
    pretty_payload = html.escape(json.dumps(payload, indent=2, ensure_ascii=False))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DiffSync Diff Report</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         margin: 0; background: #f4f5f7; color: #1c2733; }}
  header {{ background: #0b2f4f; color: #fff; padding: 24px 32px; }}
  header h1 {{ margin: 0 0 4px; font-size: 22px; }}
  header p {{ margin: 0; opacity: .8; font-size: 13px; }}
  main {{ max-width: 1080px; margin: 24px auto; padding: 0 24px 48px; }}
  section {{ background: #fff; border: 1px solid #e1e4e8; border-radius: 8px;
            padding: 20px 24px; margin-bottom: 24px; }}
  h2 {{ font-size: 16px; margin: 0 0 16px; }}
  .bar-row {{ display: flex; align-items: center; gap: 12px; margin: 8px 0; }}
  .bar-label {{ width: 90px; font-size: 13px; text-transform: capitalize; }}
  .bar-track {{ flex: 1; background: #eef0f2; border-radius: 4px; height: 18px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 4px; }}
  .bar-count {{ width: 32px; text-align: right; font-variant-numeric: tabular-nums; }}
  ul {{ list-style: none; margin: 6px 0 6px 18px; padding-left: 18px;
        border-left: 1px dashed #c7ccd1; }}
  li {{ margin: 6px 0; }}
  .badge {{ display: inline-block; min-width: 64px; text-align: center; color: #fff;
           font-size: 11px; padding: 2px 8px; border-radius: 10px; margin-right: 8px;
           text-transform: uppercase; letter-spacing: .04em; }}
  .node {{ font-family: "SFMono-Regular", Consolas, monospace; font-size: 13px; }}
  .attrs {{ font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; color: #57606a; }}
  pre {{ background: #0d1117; color: #c9d1d9; padding: 16px; border-radius: 8px;
         overflow: auto; font-size: 12px; line-height: 1.45; }}
  .muted {{ color: #636c76; font-size: 12px; }}
</style>
</head>
<body>
<header>
  <h1>DiffSync Diff Report</h1>
  <p>Action distribution and children tree of an example Diff, rendered from its
     versioned <code>dict()</code> payload.</p>
</header>
<main>
  <section>
    <h2>Action distribution</h2>
    {''.join(bars)}
    <p class="muted">Counts cover all elements present in the in-memory Diff, including
       <code>action = None</code> containers (shown as "no-change"). Elements that are no-change
       and have no diffing children are omitted from the serialized payload below.</p>
  </section>
  <section>
    <h2>Children tree</h2>
    <ul>{tree_items}</ul>
  </section>
  <section>
    <h2>Serialized payload (<code>Diff.dict()</code>, round-tripped via <code>from_dict()</code>)</h2>
    <pre>{pretty_payload}</pre>
  </section>
</main>
</body>
</html>
"""


def main():
    """Build the example Diff, round-trip it, and write the static HTML report."""
    diff = build_example_diff()
    # Round-trip through the serialization layer: the report reflects exactly what can be replayed.
    payload = Diff.from_dict(diff.dict()).dict()
    REPORT_PATH.write_text(render_html(diff, payload), encoding="utf-8")
    print(f"Wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
