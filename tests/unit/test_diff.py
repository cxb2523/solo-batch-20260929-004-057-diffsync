"""Unit tests for the Diff class.

Copyright (c) 2020-2021 Network To Code, LLC <info@networktocode.com>

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import json

import pytest

from diffsync.diff import Diff, DiffElement
from diffsync.exceptions import ObjectAlreadyExists


def test_diff_empty():
    """Test the basic functionality of the Diff class when initialized and empty."""
    diff = Diff()

    assert not diff.children
    assert not list(diff.groups())
    assert not diff.has_diffs()
    assert not list(diff.get_children())


def test_diff_summary_with_no_diffs():
    diff = Diff()

    assert diff.summary() == {"create": 0, "update": 0, "delete": 0, "no-change": 0, "skip": 0}


def test_diff_str_with_no_diffs():
    diff = Diff()

    assert diff.str() == "(no diffs)"


def test_diff_dict_with_no_diffs():
    diff = Diff()

    assert not diff.dict()


def test_diff_len_with_no_diffs():
    diff = Diff()

    assert len(diff) == 0


def test_diff_children():
    """Test the basic functionality of the Diff class when adding child elements."""
    diff = Diff()
    device_element = DiffElement("device", "device1", {"name": "device1"})
    intf_element = DiffElement("interface", "eth0", {"device_name": "device1", "name": "eth0"})

    diff.add(device_element)
    assert "device" in diff.children
    assert diff.children["device"] == {"device1": device_element}
    assert list(diff.groups()) == ["device"]
    assert not diff.has_diffs()
    assert list(diff.get_children()) == [device_element]
    with pytest.raises(ObjectAlreadyExists):
        diff.add(device_element)

    diff.add(intf_element)
    assert "interface" in diff.children
    assert diff.children["interface"] == {"eth0": intf_element}
    assert list(diff.groups()) == ["device", "interface"]
    assert not diff.has_diffs()
    assert list(diff.get_children()) == [device_element, intf_element]
    with pytest.raises(ObjectAlreadyExists):
        diff.add(intf_element)

    source_attrs = {"interface_type": "ethernet", "description": "my interface"}
    dest_attrs = {"description": "your interface"}
    intf_element.add_attrs(source=source_attrs, dest=dest_attrs)

    assert diff.has_diffs()


def test_diff_summary_with_diffs(diff_with_children):
    # Create person "Jimbo"
    # Delete person "Sully"
    # Update interface "device1_eth0"
    # No change to address "RTP" and device "device1"
    assert diff_with_children.summary() == {"create": 1, "update": 1, "delete": 1, "no-change": 2, "skip": 0}


def test_diff_str_with_diffs(diff_with_children):
    # Since the address element has no diffs, we don't have any "address" entry in the diff string:
    assert (
        diff_with_children.str()
        == """\
person
  person: Jimbo MISSING in dest
  person: Sully MISSING in source
device
  device: device1
    interface
      interface: eth0
        description    source(my interface)    dest(your interface)\
"""
    )


def test_diff_dict_with_diffs(diff_with_children):
    # Since the address element has no diffs, we don't have any "address" entry in the diff dict:
    assert diff_with_children.dict() == {
        "device": {
            "device1": {
                "interface": {"eth0": {"+": {"description": "my interface"}, "-": {"description": "your interface"}}}
            }
        },
        "person": {"Jimbo": {"+": {}}, "Sully": {"-": {}}},
    }


def test_diff_len_with_diffs(diff_with_children):
    assert len(diff_with_children) == 5
    assert len(diff_with_children) == sum(count for count in diff_with_children.summary().values())


def test_order_children_default(backend_a, backend_b):
    """Test that order_children_default is properly called when calling get_children."""

    class MyDiff(Diff):
        """custom diff class to test order_children_default."""

        @classmethod
        def order_children_default(cls, children):
            """Return the children ordered in alphabetical order."""
            keys = sorted(children.keys(), reverse=False)
            for key in keys:
                yield children[key]

    # Validating default order method
    diff_a_b = backend_a.diff_from(backend_b, diff_class=MyDiff)
    children = diff_a_b.get_children()
    children_names = [child.name for child in children]
    assert children_names == ["atl", "nyc", "rdu", "sfo"]


def test_order_children_custom(backend_a, backend_b):
    """Test that a custom order_children method is properly called when calling get_children."""

    class MyDiff(Diff):
        """custom diff class to test order_children_site."""

        @classmethod
        def order_children_site(cls, children):
            """Return the site children ordered in reverse-alphabetical order."""
            keys = sorted(children.keys(), reverse=True)
            for key in keys:
                yield children[key]

    diff_a_b = backend_a.diff_from(backend_b, diff_class=MyDiff)
    children = diff_a_b.get_children()
    children_names = [child.name for child in children]
    assert children_names == ["sfo", "rdu", "nyc", "atl"]


def test_diff_add_same_path_create_then_update():
    """A create record followed by an update record for the same path merges into a single create."""
    diff = Diff()

    create_element = DiffElement("device", "device1", {"name": "device1"})
    create_element.add_attrs(source={"role": "switch"})
    create_child = DiffElement("interface", "eth0", {"device_name": "device1", "name": "eth0"})
    create_child.add_attrs(source={"description": "first"})
    create_element.add_child(create_child)
    diff.add(create_element)

    update_element = DiffElement("device", "device1", {"name": "device1"})
    update_element.add_attrs(source={"role": "router"}, dest={"role": "switch"})
    update_child = DiffElement("interface", "eth1", {"device_name": "device1", "name": "eth1"})
    update_child.add_attrs(source={"description": "second"})
    update_element.add_child(update_child)
    diff.add(update_element)  # must not raise ObjectAlreadyExists

    # A single element remains mounted at the device/device1 path
    assert list(diff.children["device"].keys()) == ["device1"]
    merged = diff.children["device"]["device1"]
    # The object still does not exist on the dest side: it stays a create, with the latest source attrs
    assert merged.action == "create"
    assert merged.source_attrs == {"role": "router"}
    assert merged.dest_attrs is None
    # Child subtrees from both records are merged, not overwritten
    assert list(merged.child_diff.children["interface"].keys()) == ["eth0", "eth1"]

    # Re-adding the exact same element object is still an error
    with pytest.raises(ObjectAlreadyExists):
        diff.add(merged)


def test_diff_dict_excludes_action_none_elements():
    """Elements with action None and no child diffs are excluded from dict()/from_dict()."""
    diff = Diff()
    no_change = DiffElement("device", "device1", {"name": "device1"})
    no_change.add_attrs(source={"role": "switch"}, dest={"role": "switch"})
    diff.add(no_change)

    assert diff.dict() == {}
    restored = Diff.from_dict(diff.dict())
    assert not restored.has_diffs()
    assert list(restored.get_children()) == []

    # A no-change parent carrying child diffs keeps action None after a round-trip,
    # so no spurious create/update would be dispatched to the store on replay.
    diff = Diff()
    parent = DiffElement("site", "site1", {"name": "site1"})
    child = DiffElement("device", "device1", {"name": "device1"})
    child.add_attrs(source={"role": "switch"})
    parent.add_child(child)
    diff.add(parent)

    # The parent has no attrs sections at all in the serialized form
    assert diff.dict() == {"site": {"site1": {"device": {"device1": {"+": {"role": "switch"}}}}}}

    restored = Diff.from_dict(diff.dict())
    restored_parent = restored.children["site"]["site1"]
    assert restored_parent.action is None
    assert restored_parent.source_attrs is None
    assert restored_parent.dest_attrs is None
    assert restored.summary() == diff.summary()
    assert restored.dict() == diff.dict()

    # A no-change leaf element (identical attrs on both sides, no child diffs) is not serialized
    # at all, so it cannot be misjudged as a create/update after a round-trip.
    equal_parent = DiffElement("site", "site2", {"name": "site2"})
    equal_parent.add_attrs(source={"region": "east"}, dest={"region": "east"})
    diff.add(equal_parent)
    assert "site2" not in diff.dict()["site"]
    restored = Diff.from_dict(diff.dict())
    assert "site2" not in restored.children["site"]
    assert restored.dict() == diff.dict()


def test_diff_dict_from_dict_deep_nesting_roundtrip():
    """A deeply nested Diff survives dict() -> from_dict() with actions and children intact."""
    diff = Diff()

    site = DiffElement("site", "nyc", {"name": "nyc"})
    site.add_attrs(source={"region": "east"}, dest={"region": "west"})  # update
    device = DiffElement("device", "nyc-spine1", {"name": "nyc-spine1"})
    device.add_attrs(source={"role": "spine"})  # create
    intf = DiffElement("interface", "eth0", {"device_name": "nyc-spine1", "name": "eth0"})
    intf.add_attrs(source={"description": "new"}, dest={"description": "old"})  # update
    loopback = DiffElement("interface", "lo0", {"device_name": "nyc-spine1", "name": "lo0"})
    loopback.add_attrs(dest={"description": "Loopback"})  # delete
    device.add_child(intf)
    device.add_child(loopback)
    site.add_child(device)
    diff.add(site)

    # Simulate persistence: the serialized form must survive a JSON round-trip
    data = json.loads(json.dumps(diff.dict()))
    restored = Diff.from_dict(data)

    assert restored.dict() == data
    restored_site = restored.children["site"]["nyc"]
    assert restored_site.action == "update"
    restored_device = restored_site.child_diff.children["device"]["nyc-spine1"]
    assert restored_device.action == "create"
    restored_intf = restored_device.child_diff.children["interface"]["eth0"]
    assert restored_intf.action == "update"
    assert restored_intf.source_attrs == {"description": "new"}
    assert restored_intf.dest_attrs == {"description": "old"}
    restored_loopback = restored_device.child_diff.children["interface"]["lo0"]
    assert restored_loopback.action == "delete"

    # A second round-trip is stable (idempotent)
    assert Diff.from_dict(restored.dict()).dict() == data
