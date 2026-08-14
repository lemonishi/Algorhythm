import pytest

from algorhythm.catalog.visualize import (
    render_grid,
    render_linked_list,
    render_tree,
    visualize,
)


def test_empty_tree_says_so():
    assert render_tree([]) == "(empty tree)"


def test_single_node_tree():
    assert render_tree([1]) == "1"


def test_three_node_tree_is_laid_out_exactly():
    assert render_tree([1, 2, 3]) == "  1\n / \\\n2   3"


def test_unbalanced_tree_places_every_value():
    out = render_tree([3, 9, 20, None, None, 15, 7])
    for value in ("3", "9", "20", "15", "7"):
        assert value in out


def test_a_distant_child_is_connected_to_its_parent():
    """A branch must reach its child, not dangle beside the parent.

    In-order layout puts a child arbitrarily far from its parent, so a lone
    slash next to the parent points at empty space — the reader cannot tell
    which node below it belongs to. The horizontal run bridges the gap and
    the elbow lands adjacent to the child it names.
    """
    assert render_tree([3, 9, 20, None, None, 15, 7]) == "\n".join(
        [
            "  3",
            " /____\\",
            "9      20",
            "      /  \\",
            "    15    7",
        ]
    )


def test_an_adjacent_child_gets_no_horizontal_run():
    """Nothing to bridge when the elbow already touches the parent."""
    assert "_" not in render_tree([1, 2, 3])


def test_tree_root_is_on_the_first_line():
    assert render_tree([3, 9, 20, None, None, 15, 7]).splitlines()[0].strip() == "3"


def test_tree_depth_determines_line_count():
    """Depth 3 tree: three value rows plus two connector rows."""
    assert len(render_tree([1, 2, 3, 4, 5, 6, 7]).splitlines()) == 5


def test_tree_handles_negative_and_multidigit_values():
    out = render_tree([100, -50, 250])
    assert "100" in out and "-50" in out and "250" in out


def test_no_line_has_trailing_whitespace():
    for line in render_tree([3, 9, 20, None, None, 15, 7]).splitlines():
        assert line == line.rstrip()


def test_grid_renders_rows_with_spaced_cells():
    assert render_grid([[1, 1, 0], [0, 1, 0]]) == "1 1 0\n0 1 0"


def test_grid_pads_cells_to_equal_width():
    assert render_grid([[1, 10], [100, 2]]) == "  1  10\n100   2"


def test_empty_grid_says_so():
    assert render_grid([]) == "(empty grid)"


def test_linked_list_uses_arrows():
    assert render_linked_list([1, 2, 3]) == "1 -> 2 -> 3 -> null"


def test_empty_linked_list_is_just_null():
    assert render_linked_list([]) == "null"


def test_visualize_dispatches_on_kind():
    assert visualize([1, 2, 3], "tree") == render_tree([1, 2, 3])
    assert visualize([[1]], "grid") == render_grid([[1]])
    assert visualize([1, 2], "linked_list") == render_linked_list([1, 2])


def test_visualize_returns_none_for_raw_values():
    """Nothing structural to draw for a plain int or string."""
    assert visualize(42, "raw") is None


def test_visualize_returns_none_for_unknown_kinds():
    assert visualize([1], "quaternion") is None
