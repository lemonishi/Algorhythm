"""Conversion between LeetCode's JSON array notation and the object graphs
its signatures actually take.

The subtle part is `build_tree`. LeetCode's level-order encoding omits the
children of null nodes rather than padding them, so a naive
`2*i+1` index scheme builds the wrong tree for anything unbalanced. The
queue-based construction below is the correct reading.
"""

from __future__ import annotations

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


def build_linked_list(values: list[Any] | None) -> ListNode | None:
    head: ListNode | None = None
    tail: ListNode | None = None
    for value in values or []:
        node = ListNode(value)
        if head is None:
            head = tail = node
        else:
            tail.next = node
            tail = node
    return head


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


_DECODERS = {
    "raw": lambda v: v,
    "grid": lambda v: v,
    "tree": build_tree,
    "linked_list": build_linked_list,
}

_ENCODERS = {
    "raw": lambda v: v,
    "grid": lambda v: v,
    "tree": serialize_tree,
    "linked_list": serialize_linked_list,
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
