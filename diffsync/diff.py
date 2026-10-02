"""Diff and DiffElement classes for DiffSync.

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

from functools import total_ordering
from typing import Any, Dict, Iterable, Iterator, List, Optional, Type

from .enum import DiffSyncActions
from .exceptions import DiffDeserializationError, ObjectAlreadyExists
from .utils import OrderedDefaultDict, intersection

# This workaround is used because we are defining a method called `str` in our class definition, which therefore renders
# the builtin `str` type unusable.
StrType = str

# Version of the self-describing, round-trippable serialization produced by Diff.dict()/DiffElement.dict().
# Bump this whenever the on-dict shape changes in a way that older code cannot safely read.
DIFF_VERSION = 1


class Diff:
    """Diff Object, designed to store multiple DiffElement object and organize them in a group."""

    def __init__(self) -> None:
        """Initialize a new, empty Diff object."""
        self.children = OrderedDefaultDict[StrType, Dict[StrType, DiffElement]](dict)
        """DefaultDict for storing DiffElement objects.

        `self.children[group][unique_id] == DiffElement(...)`
        """
        self.models_processed = 0

    def __len__(self) -> int:
        """Total number of DiffElements stored herein."""
        total = 0
        for child in self.get_children():
            total += len(child)
        return total

    def complete(self) -> None:
        """Method to call when this Diff has been fully populated with data and is "complete".

        The default implementation does nothing, but a subclass could use this, for example, to save
        the completed Diff to a file or database record.
        """

    def add(self, element: "DiffElement") -> None:
        """Add a new DiffElement to the changeset of this Diff.

        If an element of the same type and name was previously added (for example, a "create" record
        that is later supplemented with the destination attributes and therefore becomes an
        "update"), the new element is merged into the existing one -- its missing source/dest
        attributes are filled in and its child elements are merged recursively -- rather than
        overwriting the existing element (and silently dropping its children).

        Raises:
            ObjectAlreadyExists: if an element of the same type and same name is already stored and
                the new element contributes no additional information.
        """
        # Note that element.name is usually a DiffSyncModel.shortname() -- i.e., NOT guaranteed globally unique!!
        existing = self.children[element.type].get(element.name)
        if existing is not None:
            if not existing.merge(element):
                raise ObjectAlreadyExists(f"Already storing a {element.type} named {element.name}", existing)
            return

        self.children[element.type][element.name] = element

    def groups(self) -> List[StrType]:
        """Get the list of all group keys in self.children."""
        return list(self.children.keys())

    def has_diffs(self) -> bool:
        """Indicate if at least one of the child elements contains some diff.

        Returns:
            True if at least one child element contains some diff
        """
        for group in self.groups():
            for child in self.children[group].values():
                if child.has_diffs(include_children=True):
                    return True

        return False

    def get_children(self) -> Iterator["DiffElement"]:
        """Iterate over all child elements in all groups in self.children.

        For each group of children, check if an order method is defined,
        Otherwise use the default method.
        """
        order_default = "order_children_default"

        for group in self.groups():
            order_method_name = f"order_children_{group}"
            if hasattr(self, order_method_name):
                order_method = getattr(self, order_method_name)
            else:
                order_method = getattr(self, order_default)

            yield from order_method(self.children[group])

    @classmethod
    def order_children_default(cls, children: Dict[StrType, "DiffElement"]) -> Iterator["DiffElement"]:
        """Default method to an Iterator for children.

        Since children is already an OrderedDefaultDict, this method is not doing anything special.
        """
        yield from children.values()

    def summary(self) -> Dict[StrType, int]:
        """Build a dict summary of this Diff and its child DiffElements."""
        summary = {
            DiffSyncActions.CREATE: 0,
            DiffSyncActions.UPDATE: 0,
            DiffSyncActions.DELETE: 0,
            "no-change": 0,
        }
        for child in self.get_children():
            child_summary = child.summary()
            for key in summary:
                summary[key] += child_summary[key]
        summary[DiffSyncActions.SKIP] = (
            self.models_processed
            - summary[DiffSyncActions.CREATE]
            # Updated elements are doubly accumulated in models_processed as they exist in SCR and DST.
            - 2 * summary[DiffSyncActions.UPDATE]
            - summary[DiffSyncActions.DELETE]
            # 'no-change' elements are doubly accumulated in models_processed as they exist in SCR and DST.
            - 2 * summary["no-change"]
        )
        return summary

    def str(self, indent: int = 0) -> StrType:
        """Build a detailed string representation of this Diff and its child DiffElements."""
        margin = " " * indent
        output = []
        for group in self.groups():
            group_heading_added = False
            for child in self.children[group].values():
                if child.has_diffs(include_children=True):
                    if not group_heading_added:
                        output.append(f"{margin}{group}")
                        group_heading_added = True
                    output.append(child.str(indent + 2))
        result = "\n".join(output)
        if not result:
            result = "(no diffs)"
        return result

    def dict(self) -> Dict[StrType, Any]:
        """Build a self-describing, round-trippable dictionary representation of this Diff.

        The output is an explicitly versioned envelope::

            {"version": 1, "diff": {<type>: {<name>: <element-dict>, ...}, ...}}

        Only elements that actually contain a diff (directly or via their children) are included;
        elements with an ``action`` of ``None`` and without any diffing children are omitted so that
        replaying a deserialized Diff does not issue spurious writes.

        Use :meth:`from_dict` to reconstruct a Diff from this representation.
        """
        result = OrderedDefaultDict[str, Dict](dict)
        for child in self.get_children():
            if child.has_diffs(include_children=True):
                result[child.type][child.name] = child.dict()
        return {"version": DIFF_VERSION, "diff": dict(result)}

    @classmethod
    def from_dict(
        cls,
        data: Dict[StrType, Any],
        *,
        source_name: Optional[StrType] = None,
        dest_name: Optional[StrType] = None,
    ) -> "Diff":
        """Reconstruct a Diff from data previously produced by :meth:`dict`.

        Args:
            data: Dictionary as produced by :meth:`Diff.dict`.
            source_name: Optional override for the source adapter name recorded on every element.
            dest_name: Optional override for the destination adapter name recorded on every element.

        Raises:
            DiffDeserializationError: if ``data`` is not a versioned Diff dictionary -- for example,
                if it uses the older unversioned/display-only dict shape, is missing required fields,
                or carries an unsupported ``version``. Old files fail loudly here rather than being
                silently misread and replayed as bogus creates/updates.
        """
        cls._require_versioned_payload(data, context="Diff")

        diff = cls()
        children = data["diff"]
        if not isinstance(children, dict):
            raise DiffDeserializationError('invalid serialized Diff: "diff" must be a dictionary')
        for obj_type, by_name in children.items():
            if not isinstance(by_name, dict):
                raise DiffDeserializationError(f'invalid serialized Diff group "{obj_type}": expected a dictionary')
            for name, element_data in by_name.items():
                # The outer (type, name) keys are authoritative; cross-check them against the payload.
                element = DiffElement.from_dict(
                    element_data,
                    obj_type=obj_type,
                    name=name,
                    diff_class=cls,
                    source_name=source_name,
                    dest_name=dest_name,
                )
                diff.add(element)
        return diff

    @staticmethod
    def _require_versioned_payload(data: Any, context: StrType) -> None:
        """Validate that ``data`` is a versioned Diff payload and not legacy/display-only data."""
        if not isinstance(data, dict):
            raise DiffDeserializationError(
                f"cannot deserialize {context} from {type(data).__name__}: expected a dictionary"
            )
        if "version" not in data:
            raise DiffDeserializationError(
                "unversioned Diff data is not supported; this looks like a legacy "
                '(display-only) Diff.dict() format - expected a {"version": ..., ...} envelope'
            )
        version = data["version"]
        if version != DIFF_VERSION:
            raise DiffDeserializationError(
                f"unsupported Diff serialization version {version!r}; expected {DIFF_VERSION}"
            )


@total_ordering
class DiffElement:  # pylint: disable=too-many-instance-attributes
    """DiffElement object, designed to represent a single item/object that may or may not have any diffs."""

    def __init__(  # pylint: disable=too-many-positional-arguments
        self,
        obj_type: StrType,
        name: StrType,
        keys: Dict,
        source_name: StrType = "source",
        dest_name: StrType = "dest",
        diff_class: Type[Diff] = Diff,
    ):  # pylint: disable=too-many-arguments
        """Instantiate a DiffElement.

        Args:
            obj_type: Name of the object type being described, as in DiffSyncModel.get_type().
            name: Human-readable name of the object being described, as in DiffSyncModel.get_shortname().
                This name must be unique within the context of the Diff that is the direct parent of this DiffElement.
            keys: Primary keys and values uniquely describing this object, as in DiffSyncModel.get_identifiers().
            source_name: Name of the source DiffSync object
            dest_name: Name of the destination DiffSync object
            diff_class: Diff or subclass thereof to use to calculate the diffs to use for synchronization
        """
        if not isinstance(obj_type, StrType):
            raise ValueError(f"obj_type must be a string (not {type(obj_type)})")

        if not isinstance(name, StrType):
            raise ValueError(f"name must be a string (not {type(name)})")

        self.type = obj_type
        self.name = name
        self.keys = keys
        self.source_name = source_name
        self.dest_name = dest_name
        # Note: *_attrs == None if no target object exists; it'll be an empty dict if it exists but has no _attributes
        self.source_attrs: Optional[Dict] = None
        self.dest_attrs: Optional[Dict] = None
        self.child_diff = diff_class()

    def __lt__(self, other: "DiffElement") -> bool:
        """Logical ordering of DiffElements.

        Other comparison methods (__gt__, __le__, __ge__, etc.) are created by our use of the @total_ordering decorator.
        """
        return (self.type, self.name) < (other.type, other.name)

    def __eq__(self, other: object) -> bool:
        """Logical equality of DiffElements.

        Other comparison methods (__gt__, __le__, __ge__, etc.) are created by our use of the @total_ordering decorator.
        """
        if not isinstance(other, DiffElement):
            return NotImplemented
        return (
            self.type == other.type
            and self.name == other.name
            and self.keys == other.keys
            and self.source_attrs == other.source_attrs
            and self.dest_attrs == other.dest_attrs
            # TODO also check that self.child_diff == other.child_diff, needs Diff to implement __eq__().
        )

    def __str__(self) -> StrType:
        """Basic string representation of a DiffElement."""
        return (
            f'{self.type} "{self.name}" : {self.keys} : '
            f"{self.source_name} → {self.dest_name} : {self.get_attrs_diffs()}"
        )

    def __len__(self) -> int:
        """Total number of DiffElements in this one, including itself."""
        total = 1  # self
        for child in self.get_children():
            total += len(child)
        return total

    @property
    def action(self) -> Optional[StrType]:
        """Action, if any, that should be taken to remediate the diffs described by this element.

        Returns:
            "create", "update", "delete", or None)
        """
        if self.source_attrs is not None and self.dest_attrs is None:
            return DiffSyncActions.CREATE
        if self.source_attrs is None and self.dest_attrs is not None:
            return DiffSyncActions.DELETE
        if (
            self.source_attrs is not None
            and self.dest_attrs is not None
            and any(self.source_attrs[attr_key] != self.dest_attrs[attr_key] for attr_key in self.get_attrs_keys())
        ):
            return DiffSyncActions.UPDATE

        return None

    # TODO: separate into set_source_attrs() and set_dest_attrs() methods, or just use direct property access instead?
    def add_attrs(self, source: Optional[Dict] = None, dest: Optional[Dict] = None) -> None:
        """Set additional attributes of a source and/or destination item that may result in diffs."""
        # TODO: should source_attrs and dest_attrs be "write-once" properties, or is it OK to overwrite them once set?
        if source is not None:
            self.source_attrs = source

        if dest is not None:
            self.dest_attrs = dest

    def get_attrs_keys(self) -> Iterable[StrType]:
        """Get the list of shared attrs between source and dest, or the attrs of source or dest if only one is present.

        - If source_attrs is not set, return the keys of dest_attrs
        - If dest_attrs is not set, return the keys of source_attrs
        - If both are defined, return the intersection of both keys
        """
        if self.source_attrs is not None and self.dest_attrs is not None:
            return intersection(list(self.dest_attrs.keys()), list(self.source_attrs.keys()))
        if self.source_attrs is None and self.dest_attrs is not None:
            return self.dest_attrs.keys()
        if self.source_attrs is not None and self.dest_attrs is None:
            return self.source_attrs.keys()
        return []

    def get_attrs_diffs(self) -> Dict[StrType, Dict[StrType, Any]]:
        """Get the dict of actual attribute diffs between source_attrs and dest_attrs.

        Returns:
            Dictionary of the form `{"-": {key1: <value>, key2: ...}, "+": {key1: <value>, key2: ...}}`,
            where the `"-"` or `"+"` dicts may be absent.
        """
        if self.source_attrs is not None and self.dest_attrs is not None:
            return {
                "-": {
                    key: self.dest_attrs[key]
                    for key in self.get_attrs_keys()
                    if self.source_attrs[key] != self.dest_attrs[key]
                },
                "+": {
                    key: self.source_attrs[key]
                    for key in self.get_attrs_keys()
                    if self.source_attrs[key] != self.dest_attrs[key]
                },
            }
        if self.source_attrs is None and self.dest_attrs is not None:
            return {"-": {key: self.dest_attrs[key] for key in self.get_attrs_keys()}}
        if self.source_attrs is not None and self.dest_attrs is None:
            return {"+": {key: self.source_attrs[key] for key in self.get_attrs_keys()}}
        return {}

    def add_child(self, element: "DiffElement") -> None:
        """Attach a child object of type DiffElement.

        Childs are saved in a Diff object and are organized by type and name.
        """
        self.child_diff.add(element)

    def merge(self, other: "DiffElement") -> bool:
        """Merge another DiffElement describing the same object (same type/name/keys) into this one.

        This normalizes records accumulated over time for the same path -- e.g. an element first
        logged as a "create" (source attrs only) and later augmented with the destination attrs,
        turning it into an "update". Missing source/dest attributes are filled in from ``other``
        and child elements are merged recursively, so previously attached children are preserved
        instead of being overwritten.

        Args:
            other: Another DiffElement with the same type, name and ``keys``.

        Returns:
            True if ``other`` contributed new information, False if it was entirely redundant.

        Raises:
            ValueError: if ``other`` does not describe the same object (different keys) or if the
                two elements carry conflicting values for the same attribute side.
        """
        if other.type != self.type or other.name != self.name or other.keys != self.keys:
            raise ValueError(
                f"cannot merge element {other.type}:{other.name} {other.keys} into "
                f"{self.type}:{self.name} {self.keys}: type, name and keys must match"
            )

        changed = False
        if other.source_attrs is not None:
            if self.source_attrs is None:
                self.source_attrs = other.source_attrs
                changed = True
            elif self.source_attrs != other.source_attrs:
                raise ValueError(
                    f"conflicting source attributes for {self.type}:{self.name}: "
                    f"{self.source_attrs} vs {other.source_attrs}"
                )
        if other.dest_attrs is not None:
            if self.dest_attrs is None:
                self.dest_attrs = other.dest_attrs
                changed = True
            elif self.dest_attrs != other.dest_attrs:
                raise ValueError(
                    f"conflicting dest attributes for {self.type}:{self.name}: "
                    f"{self.dest_attrs} vs {other.dest_attrs}"
                )

        for other_child in other.get_children():
            existing_child = self.child_diff.children[other_child.type].get(other_child.name)
            if existing_child is None:
                # New child: attach directly without going through add(), as add() would reject a
                # genuinely new element only in error cases.
                self.child_diff.children[other_child.type][other_child.name] = other_child
                changed = True
            else:
                changed |= existing_child.merge(other_child)

        return changed

    def get_children(self) -> Iterator["DiffElement"]:
        """Iterate over all child DiffElements of this one."""
        yield from self.child_diff.get_children()

    def has_diffs(self, include_children: bool = True) -> bool:
        """Check whether this element (or optionally any of its children) has some diffs.

        Args:
          include_children: If True, recursively check children for diffs as well.
        """
        if (self.source_attrs is not None and self.dest_attrs is None) or (
            self.source_attrs is None and self.dest_attrs is not None
        ):
            return True
        if self.source_attrs is not None and self.dest_attrs is not None:
            for attr_key in self.get_attrs_keys():
                if self.source_attrs.get(attr_key) != self.dest_attrs.get(attr_key):
                    return True

        if include_children:
            if self.child_diff.has_diffs():
                return True

        return False

    def summary(self) -> Dict[StrType, int]:
        """Build a summary of this DiffElement and its children."""
        summary = {
            DiffSyncActions.CREATE: 0,
            DiffSyncActions.UPDATE: 0,
            DiffSyncActions.DELETE: 0,
            "no-change": 0,
        }
        if self.action:
            summary[self.action] += 1
        else:
            summary["no-change"] += 1
        child_summary = self.child_diff.summary()
        for key in summary:
            summary[key] += child_summary[key]
        return summary

    def str(self, indent: int = 0) -> StrType:
        """Build a detailed string representation of this DiffElement and its children."""
        margin = " " * indent
        result = f"{margin}{self.type}: {self.name}"
        if self.source_attrs is not None and self.dest_attrs is not None:
            # Only print attrs that have meaning in both source and dest
            attrs_diffs = self.get_attrs_diffs()
            for attr in attrs_diffs["+"]:
                result += (
                    f"\n{margin}  {attr}"
                    f"    {self.source_name}({attrs_diffs['+'][attr]})"
                    f"    {self.dest_name}({attrs_diffs['-'][attr]})"
                )
        elif self.dest_attrs is not None:
            result += f" MISSING in {self.source_name}"
        elif self.source_attrs is not None:
            result += f" MISSING in {self.dest_name}"

        if self.child_diff.has_diffs():
            result += "\n" + self.child_diff.str(indent + 2)
        elif self.source_attrs is None and self.dest_attrs is None:
            result += " (no diffs)"
        return result

    def dict(self) -> Dict[StrType, Any]:
        """Build a self-describing, round-trippable dictionary representation of this DiffElement.

        Shape::

            {
                "type": <obj_type>,
                "name": <name>,
                "keys": {...identifiers...},
                "source_name": <str>,
                "dest_name": <str>,
                "source_attrs": {...} or None,
                "dest_attrs": {...} or None,
                "children": {<type>: {<name>: <element-dict>, ...}, ...},
            }

        The full source/dest attribute sets (not just the diffing subset) are recorded so that
        :meth:`from_dict` can reconstruct the exact :attr:`action`; an element whose ``action`` is
        ``None`` and which has no diffing children is not emitted at all by :meth:`Diff.dict`.
        """
        children = self.child_diff.dict()["diff"]
        result: Dict[StrType, Any] = {
            "type": self.type,
            "name": self.name,
            "keys": dict(self.keys),
            "source_name": self.source_name,
            "dest_name": self.dest_name,
            "source_attrs": dict(self.source_attrs) if self.source_attrs is not None else None,
            "dest_attrs": dict(self.dest_attrs) if self.dest_attrs is not None else None,
            "children": children,
        }
        return result

    @classmethod
    def from_dict(
        cls,
        data: Dict[StrType, Any],
        *,
        obj_type: Optional[StrType] = None,
        name: Optional[StrType] = None,
        diff_class: Type[Diff] = Diff,
        source_name: Optional[StrType] = None,
        dest_name: Optional[StrType] = None,
    ) -> "DiffElement":
        """Reconstruct a DiffElement from data previously produced by :meth:`dict`.

        Args:
            data: Dictionary as produced by :meth:`DiffElement.dict`.
            obj_type: Object type implied by the enclosing :meth:`Diff.from_dict` group, if any.
                Must agree with ``data["type"]`` when both are present.
            name: Object name implied by the enclosing group, if any. Must agree with ``data["name"]``.
            diff_class: Diff class (or subclass) used for the element's child diff.
            source_name: Optional override for the source adapter name.
            dest_name: Optional override for the destination adapter name.

        Raises:
            DiffDeserializationError: if ``data`` does not follow the versioned element schema,
                uses the legacy ``{"-"/"+": ...}`` display shape, or has missing/conflicting fields.
        """
        if not isinstance(data, dict):
            raise DiffDeserializationError(
                f"cannot deserialize DiffElement from {type(data).__name__}: expected a dictionary"
            )
        # The legacy display shape only ever carries "-"/"+" attribute diffs and child groups,
        # never the identifying "keys" field. Reject it explicitly instead of misreading it.
        if "keys" not in data or "type" not in data or "name" not in data:
            raise DiffDeserializationError(
                'invalid serialized DiffElement: "type", "name" and "keys" are required; '
                "an unversioned/legacy Diff dict cannot be replayed safely"
            )

        payload_type = data["type"]
        payload_name = data["name"]
        if obj_type is not None and obj_type != payload_type:
            raise DiffDeserializationError(
                f'type mismatch in serialized DiffElement: group says "{obj_type}", payload says "{payload_type}"'
            )
        if name is not None and name != payload_name:
            raise DiffDeserializationError(
                f'name mismatch in serialized DiffElement: group says "{name}", payload says "{payload_name}"'
            )

        keys = data["keys"]
        if not isinstance(keys, dict):
            raise DiffDeserializationError('invalid serialized DiffElement: "keys" must be a dictionary')

        element_source_name = source_name or data.get("source_name", "source")
        element_dest_name = dest_name or data.get("dest_name", "dest")

        source_attrs = data.get("source_attrs")
        dest_attrs = data.get("dest_attrs")
        if source_attrs is not None and not isinstance(source_attrs, dict):
            raise DiffDeserializationError('invalid serialized DiffElement: "source_attrs" must be a dict or null')
        if dest_attrs is not None and not isinstance(dest_attrs, dict):
            raise DiffDeserializationError('invalid serialized DiffElement: "dest_attrs" must be a dict or null')

        children = data.get("children", {})
        if not isinstance(children, dict):
            raise DiffDeserializationError('invalid serialized DiffElement: "children" must be a dictionary')

        element = cls(
            obj_type=payload_type,
            name=payload_name,
            keys=keys,
            source_name=element_source_name,
            dest_name=element_dest_name,
            diff_class=diff_class,
        )
        element.add_attrs(source=source_attrs, dest=dest_attrs)

        for child_type, by_name in children.items():
            if not isinstance(by_name, dict):
                raise DiffDeserializationError(
                    f'invalid serialized children group "{child_type}": expected a dictionary'
                )
            for child_name, child_data in by_name.items():
                element.add_child(
                    cls.from_dict(
                        child_data,
                        obj_type=child_type,
                        name=child_name,
                        diff_class=diff_class,
                        source_name=source_name,
                        dest_name=dest_name,
                    )
                )

        return element
