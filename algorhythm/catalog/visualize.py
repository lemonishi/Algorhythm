"""ASCII rendering of structural inputs.

Most LeetCode diagrams illustrate data the statement already gives you as a
JSON array, so they can be redrawn from that array — deterministically, and
arguably more legibly in a terminal than the original PNG.

Tree layout uses in-order traversal for horizontal position and depth for
vertical, which is the standard approach and reads correctly for both
balanced and skewed trees.
"""

from __future__ import annotations

from typing import Any

from algorhythm.codecs.leetcode_types import TreeNode, build_tree

_COLUMN_GAP = 1


def render_tree(values: list[Any] | None) -> str:
    root = build_tree(values)
    if root is None:
        return "(empty tree)"

    positions: dict[int, tuple[int, int]] = {}
    labels: dict[int, str] = {}
    cursor = 0

    def assign(node: TreeNode, depth: int) -> None:
        nonlocal cursor
        if node.left is not None:
            assign(node.left, depth + 1)
        label = str(node.val)
        labels[id(node)] = label
        positions[id(node)] = (depth * 2, cursor)
        cursor += len(label) + _COLUMN_GAP
        if node.right is not None:
            assign(node.right, depth + 1)

    assign(root, 0)

    height = max(row for row, _ in positions.values()) + 1
    width = max(col + len(labels[key]) for key, (_, col) in positions.items()) + 1
    canvas = [[" "] * width for _ in range(height)]

    def place(row: int, col: int, text: str) -> None:
        for offset, char in enumerate(text):
            if 0 <= row < height and 0 <= col + offset < width:
                canvas[row][col + offset] = char

    def draw(node: TreeNode) -> None:
        row, col = positions[id(node)]
        label = labels[id(node)]
        place(row, col, label)
        if node.left is not None:
            place(row + 1, col - 1, "/")
            draw(node.left)
        if node.right is not None:
            place(row + 1, col + len(label), "\\")
            draw(node.right)

    draw(root)
    return "\n".join("".join(row).rstrip() for row in canvas).rstrip("\n")


def render_grid(rows: list[list[Any]] | None) -> str:
    if not rows:
        return "(empty grid)"
    cells = [[str(value) for value in row] for row in rows]
    width = max((len(cell) for row in cells for cell in row), default=1)
    return "\n".join(" ".join(cell.rjust(width) for cell in row) for row in cells)


def render_linked_list(values: list[Any] | None) -> str:
    if not values:
        return "null"
    return " -> ".join(str(value) for value in values) + " -> null"


def visualize(value: Any, kind: str) -> str | None:
    """Return an ASCII drawing for structural kinds, or None when there is
    nothing worth drawing."""
    if kind == "tree":
        return render_tree(value)
    if kind == "grid":
        return render_grid(value)
    if kind == "linked_list":
        return render_linked_list(value)
    return None
