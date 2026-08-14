"""Conversion between LeetCode's JSON array notation and the object graphs
its signatures actually take.

The subtle part is `build_tree`. LeetCode's level-order encoding omits the
children of null nodes rather than padding them, so a naive
`2*i+1` index scheme builds the wrong tree for anything unbalanced. The
queue-based construction below is the correct reading.
"""

from __future__ import annotations

import json
from collections import deque
from typing import Any


class TreeNode:
    __slots__ = ("val", "left", "right")

    def __init__(self, val: Any = 0, left=None, right=None) -> None:
        self.val = val
        self.left = left
        self.right = right

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"TreeNode({self.val!r})"


class ListNode:
    __slots__ = ("val", "next")

    def __init__(self, val: Any = 0, next=None) -> None:  # noqa: A002
        self.val = val
        self.next = next

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ListNode({self.val!r})"


def build_tree(values: list[Any] | None) -> TreeNode | None:
    if not values or values[0] is None:
        return None

    root = TreeNode(values[0])
    queue = deque([root])
    index = 1

    while queue and index < len(values):
        node = queue.popleft()

        if index < len(values):
            value = values[index]
            index += 1
            if value is not None:
                node.left = TreeNode(value)
                queue.append(node.left)

        if index < len(values):
            value = values[index]
            index += 1
            if value is not None:
                node.right = TreeNode(value)
                queue.append(node.right)

    return root


def serialize_tree(root: TreeNode | None) -> list[Any]:
    if root is None:
        return []

    out: list[Any] = []
    queue = deque([root])
    while queue:
        node = queue.popleft()
        if node is None:
            out.append(None)
            continue
        out.append(node.val)
        queue.append(node.left)
        queue.append(node.right)

    while out and out[-1] is None:
        out.pop()
    return out


def build_linked_list(values: list[Any] | dict | None) -> ListNode | None:
    """A list from `[1,2,3]`, or a cycle from `{"values": [...], "pos": n}`.

    JSON cannot express a cycle, and LeetCode states one out of band: its
    linked-list-cycle examples read `head = [3,2,0,-4], pos = 1`, where `pos`
    is the index the tail points back to and `-1` means no cycle. The dict
    form is how a curated test case carries that second value, since `pos`
    is not a parameter of the signature under test.
    """
    position = -1
    if isinstance(values, dict):
        position = values.get("pos", -1)
        values = values.get("values")

    nodes = [ListNode(value) for value in values or []]
    for node, following in zip(nodes, nodes[1:]):
        node.next = following
    if nodes and 0 <= position < len(nodes):
        nodes[-1].next = nodes[position]
    return nodes[0] if nodes else None


def serialize_linked_list(head: ListNode | None) -> list[Any]:
    out: list[Any] = []
    seen: set[int] = set()
    node = head
    while node is not None:
        if id(node) in seen:  # a cycle; stop rather than hang
            break
        seen.add(id(node))
        out.append(node.val)
        node = node.next
    return out


class Node:
    """LeetCode's undirected-graph node, as used by clone-graph."""

    __slots__ = ("val", "neighbors")

    def __init__(self, val: Any = 0, neighbors=None) -> None:
        self.val = val
        self.neighbors = neighbors if neighbors is not None else []

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Node({self.val!r})"


def build_graph(adjacency: list[list[int]] | None) -> Node | None:
    """Adjacency lists to a node graph, 1-indexed as LeetCode writes them.

    Entry `i` lists the neighbours of the node whose `val` is `i + 1`, so
    `[[2,4],[1,3],[2,4],[1,3]]` is a four-node square. The first node is
    returned because that is what the signature takes.
    """
    if not adjacency:
        return None
    nodes = [Node(index + 1) for index in range(len(adjacency))]
    for node, neighbours in zip(nodes, adjacency):
        node.neighbors = [nodes[value - 1] for value in neighbours]
    return nodes[0]


def serialize_graph(node: Node | None) -> list[list[int]]:
    """Back to adjacency lists, ordered by `val`.

    Ordering by val rather than by traversal is what makes a correct clone
    compare equal to the input: the walk order depends on how the solution
    happened to build its copy, and that is not part of the answer.
    """
    if node is None:
        return []

    adjacency: dict[int, list[int]] = {}
    queue = deque([node])
    seen = {node.val}
    while queue:
        current = queue.popleft()
        values = []
        for neighbour in current.neighbors:
            values.append(neighbour.val)
            if neighbour.val not in seen:
                seen.add(neighbour.val)
                queue.append(neighbour)
        adjacency[current.val] = values

    return [adjacency[key] for key in sorted(adjacency)]


_DECODERS = {
    "raw": lambda v: v,
    "grid": lambda v: v,
    "tree": build_tree,
    "linked_list": build_linked_list,
    "graph": build_graph,
}

_ENCODERS = {
    "raw": lambda v: v,
    "grid": lambda v: v,
    "tree": serialize_tree,
    "linked_list": serialize_linked_list,
    "graph": serialize_graph,
}


# Membership is checked before dispatch rather than wrapping the call in
# `except KeyError`: the wrapper would report a KeyError raised *inside* a
# codec as "unknown kind", which is a lie that costs a debugging session.
def decode(value: Any, kind: str) -> Any:
    """JSON -> the object the solution expects."""
    if kind not in _DECODERS:
        raise ValueError(f"unknown kind: {kind}")
    return _DECODERS[kind](value)


def encode(value: Any, kind: str) -> Any:
    """The object the solution returned -> comparable JSON."""
    if kind not in _ENCODERS:
        raise ValueError(f"unknown kind: {kind}")
    return _ENCODERS[kind](value)


def normalize(value: Any, comparison: str) -> Any:
    """Put a value in the form its comparison mode compares.

    Under `unordered` every list is sorted, at every level of nesting, so
    `[["eat","tea"],["bat"]]` and `[["bat"],["tea","eat"]]` become the same
    thing. Ordering is by the value's JSON text rather than by the value
    itself: `sorted()` raises on a list mixing ints and strings, and a
    comparison that raises would read to the user as a crashed solution.
    """
    if comparison != "unordered":
        return value
    return _sorted_deep(value)


def _sorted_deep(value: Any) -> Any:
    if isinstance(value, list):
        return sorted(
            (_sorted_deep(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
    return value
