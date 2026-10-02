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

import pytest

from diffsync import Adapter, DiffSyncModel
from diffsync.diff import DIFF_VERSION, Diff, DiffElement
from diffsync.enum import DiffSyncActions
from diffsync.exceptions import DiffDeserializationError, ObjectAlreadyExists


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

    assert diff.dict() == {"version": 1, "diff": {}}


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
    # Since the address element has no diffs, we don't have any "address" entry in the diff dict.
    # The format is a versioned, self-describing envelope so that from_dict() can replay it exactly.
    assert diff_with_children.dict() == {
        "version": 1,
        "diff": {
            "device": {
                "device1": {
                    "type": "device",
                    "name": "device1",
                    "keys": {"name": "device1"},
                    "source_name": "source",
                    "dest_name": "dest",
                    "source_attrs": None,
                    "dest_attrs": None,
                    "children": {
                        "interface": {
                            "eth0": {
                                "type": "interface",
                                "name": "eth0",
                                "keys": {"device_name": "device1", "name": "eth0"},
                                "source_name": "source",
                                "dest_name": "dest",
                                "source_attrs": {
                                    "interface_type": "ethernet",
                                    "description": "my interface",
                                },
                                "dest_attrs": {"description": "your interface"},
                                "children": {},
                            }
                        }
                    },
                }
            },
            "person": {
                "Jimbo": {
                    "type": "person",
                    "name": "Jimbo",
                    "keys": {"name": "Jimbo"},
                    "source_name": "source",
                    "dest_name": "dest",
                    "source_attrs": {},
                    "dest_attrs": None,
                    "children": {},
                },
                "Sully": {
                    "type": "person",
                    "name": "Sully",
                    "keys": {"name": "Sully"},
                    "source_name": "source",
                    "dest_name": "dest",
                    "source_attrs": None,
                    "dest_attrs": {},
                    "children": {},
                },
            },
        },
    }


def test_diff_len_with_diffs(diff_with_children):
    assert len(diff_with_children) == 5
    assert len(diff_with_children) == sum(count for count in diff_with_children.summary().values())


def test_diff_add_create_then_update_same_path_merges():
    """Recording a create for a path and later an update must merge, not duplicate/overwrite.

    The first element already carries a child subtree; when the second element supplies the
    missing destination attributes, the merged element must be a single "update" and must keep
    the previously attached children.
    """
    diff = Diff()

    created = DiffElement("device", "device1", {"name": "device1"})
    created.add_attrs(source={"role": "leaf"})
    child = DiffElement("interface", "eth0", {"device_name": "device1", "name": "eth0"})
    child.add_attrs(source={"description": "new"}, dest={"description": "old"})
    created.add_child(child)
    diff.add(created)
    assert created.action == "create"

    # A later pass discovers the destination object and only logs the dest side of the device.
    updated = DiffElement("device", "device1", {"name": "device1"})
    updated.add_attrs(dest={"role": "spine"})
    diff.add(updated)

    # Still exactly one device element, now an update, with the original child subtree intact.
    devices = diff.children["device"]
    assert list(devices) == ["device1"]
    merged = devices["device1"]
    assert merged is created
    assert merged.source_attrs == {"role": "leaf"}
    assert merged.dest_attrs == {"role": "spine"}
    assert merged.action == "update"
    assert list(merged.get_children()) == [child]
    assert len(diff) == 2


def test_diff_add_identical_element_twice_still_raises():
    """A purely redundant re-add of the exact same element still raises ObjectAlreadyExists."""
    diff = Diff()
    element = DiffElement("device", "device1", {"name": "device1"})
    element.add_attrs(source={"role": "leaf"}, dest={"role": "spine"})
    diff.add(element)
    with pytest.raises(ObjectAlreadyExists):
        diff.add(DiffElement("device", "device1", {"name": "device1"}))


def test_diff_add_merge_conflicting_keys_raises():
    """Merging two elements that merely share type/name but have different keys is invalid."""
    diff = Diff()
    first = DiffElement("interface", "eth0", {"device_name": "device1", "name": "eth0"})
    first.add_attrs(source={"description": "a"})
    diff.add(first)
    second = DiffElement("interface", "eth0", {"device_name": "device2", "name": "eth0"})
    second.add_attrs(source={"description": "b"})
    with pytest.raises(ValueError):
        diff.add(second)


def test_diff_add_create_then_update_via_from_dict_does_not_duplicate():
    """The deserialization path merges an existing subtree the same way add() does."""
    diff = Diff()
    created = DiffElement("device", "device1", {"name": "device1"})
    created.add_attrs(source={"role": "leaf"})
    child = DiffElement("interface", "eth0", {"device_name": "device1", "name": "eth0"})
    child.add_attrs(source={"description": "new"})
    created.add_child(child)
    diff.add(created)

    follow_up = Diff()
    updated = DiffElement("device", "device1", {"name": "device1"})
    updated.add_attrs(dest={"role": "spine"})
    follow_up.add(updated)

    # Simulate a second, deserialized chunk being folded into the first diff.
    merged_chunk = Diff.from_dict(follow_up.dict())
    for element in list(merged_chunk.get_children()):
        diff.add(element)

    assert list(diff.children["device"]) == ["device1"]
    merged = diff.children["device"]["device1"]
    assert merged.action == "update"
    assert list(merged.get_children()) == [child]


def test_diff_from_dict_rejects_legacy_unversioned_shape():
    """Old display-only dict payloads must fail loudly rather than be silently misread."""
    legacy = {"device": {"device1": {"+": {"role": "leaf"}}}}
    with pytest.raises(DiffDeserializationError):
        Diff.from_dict(legacy)


def test_diff_from_dict_rejects_unsupported_version():
    with pytest.raises(DiffDeserializationError):
        Diff.from_dict({"version": DIFF_VERSION + 99, "diff": {}})


def test_diff_from_dict_rejects_legacy_element_payload():
    """A versioned envelope whose element lacks the identifying fields must be rejected."""
    legacy_nested = {
        "version": DIFF_VERSION,
        "diff": {"device": {"device1": {"-": {"role": "spine"}, "+": {"role": "leaf"}}}},
    }
    with pytest.raises(DiffDeserializationError):
        Diff.from_dict(legacy_nested)


def test_diff_from_dict_rejects_non_mapping():
    with pytest.raises(DiffDeserializationError):
        Diff.from_dict([("version", DIFF_VERSION)])  # type: ignore[arg-type]


def test_diff_from_dict_action_none_elements_excluded_and_preserved_as_containers():
    """action=None leaves are omitted, while action=None parents with diffing children survive.

    Round-tripping must not turn a no-op element into a spurious create/update.
    """
    diff = Diff()

    # Pure no-change element: equal attrs on both sides, no children -> omitted from dict().
    no_change = DiffElement("address", "RTP", {"name": "RTP"})
    no_change.add_attrs(source={"state": "NC"}, dest={"state": "NC"})
    diff.add(no_change)

    # No-change parent (action is None) but its child has a real diff -> parent kept as container.
    parent = DiffElement("device", "device1", {"name": "device1"})
    child = DiffElement("interface", "eth0", {"device_name": "device1", "name": "eth0"})
    child.add_attrs(source={"description": "new"}, dest={"description": "old"})
    parent.add_child(child)
    diff.add(parent)

    assert parent.action is None

    serialized = diff.dict()
    assert "address" not in serialized["diff"]
    assert list(serialized["diff"]["device"]) == ["device1"]

    restored = Diff.from_dict(serialized)
    restored_parent = restored.children["device"]["device1"]
    assert restored_parent.action is None
    assert restored_parent.has_diffs(include_children=True)
    assert not restored_parent.has_diffs(include_children=False)
    restored_child = list(restored_parent.get_children())[0]
    assert restored_child.action == "update"
    assert restored.dict() == serialized


def test_diff_deep_nested_dict_roundtrip_is_lossless():
    """A site -> device -> interface tree round-trips through dict()/from_dict() losslessly."""
    diff = Diff()

    site = DiffElement("site", "nyc", {"name": "nyc"}, source_name="SRC", dest_name="DST")
    # site itself is a no-op container
    device = DiffElement("device", "nyc-spine1", {"name": "nyc-spine1"}, source_name="SRC", dest_name="DST")
    device.add_attrs(source={"role": "spine"}, dest={"role": "leaf"})
    interface_update = DiffElement(
        "interface", "eth0", {"device_name": "nyc-spine1", "name": "eth0"}, source_name="SRC", dest_name="DST"
    )
    interface_update.add_attrs(
        source={"description": "new", "interface_type": "ethernet"},
        dest={"description": "old", "interface_type": "ethernet"},
    )
    interface_create = DiffElement(
        "interface", "eth1", {"device_name": "nyc-spine1", "name": "eth1"}, source_name="SRC", dest_name="DST"
    )
    interface_create.add_attrs(source={"description": "fresh"})
    interface_delete = DiffElement(
        "interface", "eth9", {"device_name": "nyc-spine1", "name": "eth9"}, source_name="SRC", dest_name="DST"
    )
    interface_delete.add_attrs(dest={"description": "gone"})

    device.add_child(interface_update)
    device.add_child(interface_create)
    device.add_child(interface_delete)
    site.add_child(device)
    diff.add(site)

    serialized = diff.dict()
    restored = Diff.from_dict(serialized)

    # Idempotent and lossless
    assert restored.dict() == serialized
    assert Diff.from_dict(restored.dict()).dict() == serialized

    restored_site = restored.children["site"]["nyc"]
    assert restored_site.source_name == "SRC"
    assert restored_site.dest_name == "DST"
    assert restored_site.action is None
    restored_device = list(restored_site.get_children())[0]
    assert restored_device.type == "device"
    assert restored_device.action == "update"
    children_by_name = {element.name: element for element in restored_device.get_children()}
    assert set(children_by_name) == {"eth0", "eth1", "eth9"}
    assert children_by_name["eth0"].action == "update"
    assert children_by_name["eth1"].action == "create"
    assert children_by_name["eth9"].action == "delete"
    assert children_by_name["eth0"].get_attrs_diffs() == interface_update.get_attrs_diffs()


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


class _City(DiffSyncModel):
    """Minimal model for replaying diffs and counting create/update/delete writes."""

    _modelname = "city"
    _identifiers = ("name",)
    _attributes = ("population",)

    name: str
    population: int = 0


class _CityAdapter(Adapter):
    """Adapter holding only cities."""

    city = _City
    top_level = ["city"]


def _patch_city_writes(monkeypatch, counters):
    """Wrap _City create/update/delete to count the writes issued to the backing store."""
    original_create, original_update, original_delete = _City.create, _City.update, _City.delete

    def counting_create(cls, adapter, ids, attrs):
        counters[DiffSyncActions.CREATE] += 1
        return original_create(adapter=adapter, ids=ids, attrs=attrs)

    def counting_update(self, attrs):
        counters[DiffSyncActions.UPDATE] += 1
        return original_update(self, attrs)

    def counting_delete(self):
        counters[DiffSyncActions.DELETE] += 1
        return original_delete(self)

    monkeypatch.setattr(_City, "create", classmethod(counting_create))
    monkeypatch.setattr(_City, "update", counting_update)
    monkeypatch.setattr(_City, "delete", counting_delete)


def _build_adapter(name, populations):
    adapter = _CityAdapter(name=name)
    for city_name, population in populations:
        adapter.add(_City(name=city_name, population=population))
    return adapter


def test_roundtripped_diff_replay_issues_no_extra_writes(monkeypatch):
    """Replaying a dict()-roundtripped Diff must issue exactly the real create/update/delete writes.

    A no-change element (equal on both sides) must be excluded from the serialized Diff so that its
    action (None) is not mistaken for create/update after deserialization.
    """
    # NYC updates, LA unchanged, SF deleted (source only), SEA created (dest only)
    source = _build_adapter("source", [("NYC", 9), ("LA", 4), ("SF", 1)])
    dest = _build_adapter("dest", [("NYC", 8), ("LA", 4), ("SEA", 2)])

    diff = source.diff_from(dest)
    assert diff.summary()["create"] == 1
    assert diff.summary()["update"] == 1
    assert diff.summary()["delete"] == 1
    assert diff.summary()["no-change"] == 1

    # The no-change city must not survive serialization.
    serialized = diff.dict()
    assert "LA" not in serialized["diff"]["city"]

    restored = Diff.from_dict(serialized)

    # Fresh source copy to replay the deserialized diff into.
    replay_source = _build_adapter("source", [("NYC", 9), ("LA", 4), ("SF", 1)])
    replay_dest = _build_adapter("dest", [("NYC", 8), ("LA", 4), ("SEA", 2)])
    counters = {DiffSyncActions.CREATE: 0, DiffSyncActions.UPDATE: 0, DiffSyncActions.DELETE: 0}
    _patch_city_writes(monkeypatch, counters)

    replay_source.sync_from(replay_dest, diff=restored)

    # Exactly one of each write; the unchanged LA element produced no create/update/delete.
    assert counters == {
        DiffSyncActions.CREATE: 1,
        DiffSyncActions.UPDATE: 1,
        DiffSyncActions.DELETE: 1,
    }
    assert not replay_source.diff_from(replay_dest).has_diffs()
