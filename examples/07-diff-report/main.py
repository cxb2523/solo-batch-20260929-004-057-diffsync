"""Generate a static HTML report for a Diff, renderable in any browser.

Builds a diff between two in-memory adapters, then renders the action
distribution (create/update/delete/no-change) and the full children tree
into a self-contained `diff_report.html` next to this script.

Run: python main.py
"""

import html
import json
import os
from typing import List, Optional

from diffsync import Adapter, DiffSyncModel
from diffsync.diff import Diff, DiffElement


class Site(DiffSyncModel):
    """Site model containing devices."""

    _modelname = "site"
    _identifiers = ("name",)
    _attributes = ("region",)
    _children = {"device": "devices"}

    name: str
    region: str = "unset"
    devices: List = []


class Device(DiffSyncModel):
    """Device model containing interfaces."""

    _modelname = "device"
    _identifiers = ("name",)
    _attributes = ("role",)
    _children = {"interface": "interfaces"}

    name: str
    role: str = "unknown"
    site_name: Optional[str] = None
    interfaces: List = []


class Interface(DiffSyncModel):
    """Interface model."""

    _modelname = "interface"
    _identifiers = ("device_name", "name")
    _shortname = ("name",)
    _attributes = ("description", "enabled")

    device_name: str
    name: str
    description: Optional[str] = None
    enabled: bool = True


class Backend(Adapter):
    """Adapter loading sites/devices/interfaces from a nested DATA dict."""

    site = Site
    device = Device
    interface = Interface

    top_level = ["site"]

    DATA = {}

    def load(self):
        """Load the DATA class attribute into the adapter."""
        for site_name, site_data in self.DATA.items():
            site = self.site(name=site_name, region=site_data["region"])
            self.add(site)
            for device_name, device_data in site_data["devices"].items():
                device = self.device(name=device_name, site_name=site_name, role=device_data["role"])
                self.add(device)
                site.add_child(device)
                for intf_name, intf_data in device_data["interfaces"].items():
                    intf = self.interface(device_name=device_name, name=intf_name, **intf_data)
                    self.add(intf)
                    device.add_child(intf)


class SourceBackend(Backend):
    """The desired state."""

    DATA = {
        "nyc": {
            "region": "us-east",
            "devices": {
                "nyc-spine1": {
                    "role": "spine",
                    "interfaces": {
                        "eth0": {"description": "uplink to core", "enabled": True},
                        "eth1": {"description": "uplink to leaf1", "enabled": True},
                    },
                },
                "nyc-leaf1": {
                    "role": "leaf",
                    "interfaces": {
                        "eth0": {"description": "uplink to spine1", "enabled": True},
                    },
                },
            },
        },
        "sfo": {
            "region": "us-west",
            "devices": {
                "sfo-spine1": {
                    "role": "spine",
                    "interfaces": {
                        "eth0": {"description": "uplink to core", "enabled": False},
                    },
                },
            },
        },
    }


class DestBackend(Backend):
    """The current state."""

    DATA = {
        "nyc": {
            "region": "us-east-1",
            "devices": {
                "nyc-spine1": {
                    "role": "spine",
                    "interfaces": {
                        "eth0": {"description": "uplink to core", "enabled": True},
                        "eth1": {"description": "STALE uplink", "enabled": False},
                    },
                },
                "nyc-oldtor": {
                    "role": "tor",
                    "interfaces": {
                        "eth0": {"description": "decommissioned", "enabled": False},
                    },
                },
            },
        },
    }


ACTIONS = ["create", "update", "delete", "no-change"]
ACTION_COLORS = {
    "create": "#2da44e",
    "update": "#bf8700",
    "delete": "#cf222e",
    "no-change": "#6e7781",
}


def count_actions(element: DiffElement, counts: dict) -> None:
    """Recursively tally the action of an element and its children."""
    action = element.action or "no-change"
    counts[action] = counts.get(action, 0) + 1
    for child in element.get_children():
        count_actions(child, counts)


def render_element(element: DiffElement) -> str:
    """Render a DiffElement and its children as a nested HTML tree."""
    action = element.action or "no-change"
    color = ACTION_COLORS[action]
    attrs = ""
    diffs = element.get_attrs_diffs()
    if diffs:
        rows = []
        for sign, label in (("-", "dest"), ("+", "source")):
            for key, value in diffs.get(sign, {}).items():
                rows.append(f"<tr><td>{html.escape(key)}</td><td>{label}</td><td>{html.escape(repr(value))}</td></tr>")
        if rows:
            attrs = f'<table class="attrs">{"".join(rows)}</table>'
    children = "".join(render_element(child) for child in element.get_children())
    children_html = f"<ul>{children}</ul>" if children else ""
    return (
        f'<li><span class="badge" style="background:{color}">{action}</span> '
        f"<strong>{html.escape(element.type)}</strong> {html.escape(element.name)}"
        f"{attrs}{children_html}</li>"
    )


def render_report(diff: Diff, source_name: str, dest_name: str) -> str:
    """Render the full HTML report for a Diff."""
    counts = {action: 0 for action in ACTIONS}
    for child in diff.get_children():
        count_actions(child, counts)
    total = sum(counts.values()) or 1

    bars = ""
    for action in ACTIONS:
        pct = counts[action] * 100.0 / total
        bars += (
            f'<div class="bar-row"><span class="bar-label">{action}</span>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%;'
            f'background:{ACTION_COLORS[action]}"></div></div>'
            f'<span class="bar-count">{counts[action]}</span></div>'
        )

    tree = "".join(render_element(child) for child in diff.get_children())
    diff_json = html.escape(json.dumps(diff.dict(), indent=2))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>DiffSync Diff Report</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; margin: 2rem auto; max-width: 960px; color: #1f2328; }}
  h1 {{ border-bottom: 2px solid #d0d7de; padding-bottom: .3rem; }}
  .badge {{ color: #fff; border-radius: 4px; padding: 1px 8px; font-size: .8em; }}
  .bar-row {{ display: flex; align-items: center; gap: .6rem; margin: .25rem 0; }}
  .bar-label {{ width: 6.5rem; text-align: right; font-weight: 600; }}
  .bar-track {{ flex: 1; background: #eaeef2; border-radius: 4px; height: 1.1rem; }}
  .bar-fill {{ height: 100%; border-radius: 4px; min-width: 2px; }}
  .bar-count {{ width: 3rem; }}
  ul {{ list-style: none; border-left: 2px solid #d0d7de; margin-left: .6rem; padding-left: 1rem; }}
  li {{ margin: .35rem 0; }}
  table.attrs {{ border-collapse: collapse; margin: .3rem 0 .3rem 1rem; font-size: .85em; }}
  table.attrs td {{ border: 1px solid #d0d7de; padding: 2px 8px; }}
  pre {{ background: #f6f8fa; padding: 1rem; border-radius: 6px; overflow-x: auto; }}
  section {{ margin-bottom: 2.5rem; }}
</style>
</head>
<body>
<h1>DiffSync Diff Report</h1>
<p>Diff calculated from <strong>{html.escape(source_name)}</strong> (source) to <strong>{html.escape(dest_name)}</strong> (dest).</p>
<section>
  <h2>Action distribution</h2>
  {bars}
</section>
<section>
  <h2>Children tree</h2>
  <ul>{tree}</ul>
</section>
<section>
  <h2>Serialized diff (dict())</h2>
  <pre>{diff_json}</pre>
</section>
</body>
</html>
"""


def main():
    """Build the diff and write the HTML report next to this script."""
    source = SourceBackend(name="source")
    source.load()
    dest = DestBackend(name="dest")
    dest.load()

    diff = source.diff_to(dest)
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diff_report.html")
    with open(report_path, "w", encoding="utf-8") as report_file:
        report_file.write(render_report(diff, source.name, dest.name))
    print(f"Report written to {report_path}")
    print(diff.str())


if __name__ == "__main__":
    main()
