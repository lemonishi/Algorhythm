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

    def connect(node: TreeNode, child: TreeNode, *, left: bool) -> None:
        """Draw the branch from `node` down to `child`.

        In-order layout puts a child at the far edge of its own subtree, so
        the horizontal distance to the parent is unbounded and a lone slash
        beside the parent points at empty space. The elbow goes beside the
        CHILD instead — that is the end a reader has to be able to trust —
        and underscores bridge back to the parent.

        Everything lands on the connector row, leaving the value rows
        holding values alone. The bridge reaches under the parent rather
        than stopping short of it, so that a node with two distant children
        gets one unbroken branch instead of a notch beneath itself.
        """
        row, col = positions[id(node)]
        width = len(labels[id(node)])
        child_col = positions[id(child)][1]

        if left:
            elbow = child_col + len(labels[id(child)])
            adjacent = elbow == col - 1
            bridge = range(elbow + 1, col + width)
        else:
            elbow = child_col - 1
            adjacent = elbow == col + width
            bridge = range(col, elbow)

        place(row + 1, elbow, "/" if left else "\\")
        if not adjacent:  # already touching; a bridge would only add noise
            for column in bridge:
                place(row + 1, column, "_")

    def draw(node: TreeNode) -> None:
        row, col = positions[id(node)]
        place(row, col, labels[id(node)])
        if node.left is not None:
            connect(node, node.left, left=True)
            draw(node.left)
        if node.right is not None:
            connect(node, node.right, left=False)
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


def render_graph(adjacency: list[list[Any]] | None) -> str:
    """Adjacency lists, 1-indexed as LeetCode writes them.

    Drawn as a list rather than a diagram: an undirected graph has no
    canonical planar layout, and a wrong-looking picture is worse than an
    exact one that happens to be textual.
    """
    if not adjacency:
        return "(empty graph)"
    width = len(str(len(adjacency)))
    return "\n".join(
        f"{index:>{width}} -> {', '.join(str(v) for v in neighbours) or '(none)'}"
        for index, neighbours in enumerate(adjacency, start=1)
    )


def render_linked_list_cycle(values: list[Any] | None, pos: int) -> str:
    """A cycle, with the back-edge called out — `-> null` would be a lie."""
    if not values:
        return "null"
    chain = " -> ".join(str(value) for value in values)
    if 0 <= pos < len(values):
        return f"{chain} -+\n(tail points back to index {pos}, value {values[pos]})"
    return f"{chain} -> null"


def visualize(value: Any, kind: str) -> str | None:
    """Return an ASCII drawing for structural kinds, or None when there is
    nothing worth drawing."""
    if kind == "tree":
        return render_tree(value)
    if kind == "grid":
        return render_grid(value)
    if kind == "graph":
        return render_graph(value)
    if kind == "linked_list":
        if isinstance(value, dict):
            return render_linked_list_cycle(value.get("values"), value.get("pos", -1))
        return render_linked_list(value)
    return None
