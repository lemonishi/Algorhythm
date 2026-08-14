import pytest

from algorhythm.codecs.leetcode_types import (
    ListNode,
    TreeNode,
    build_linked_list,
    build_tree,
    decode,
    encode,
    serialize_linked_list,
    serialize_tree,
)


# -- trees ----------------------------------------------------------------

def test_build_tree_of_empty_list_is_none():
    assert build_tree([]) is None


def test_build_tree_of_explicit_null_is_none():
    assert build_tree([None]) is None


def test_build_tree_sets_children_in_level_order():
    root = build_tree([1, 2, 3])
    assert root.val == 1
    assert root.left.val == 2
    assert root.right.val == 3


def test_build_tree_skips_null_children():
    """[3,9,20,null,null,15,7]: 9 is a leaf, so 15 and 7 belong to 20.
    Getting this wrong silently builds the wrong tree."""
    root = build_tree([3, 9, 20, None, None, 15, 7])
    assert root.left.val == 9
    assert root.left.left is None
    assert root.left.right is None
    assert root.right.left.val == 15
    assert root.right.right.val == 7


def test_build_tree_handles_a_left_leaning_chain():
    root = build_tree([1, 2, None, 3, None, 4])
    assert root.left.val == 2
    assert root.left.left.val == 3
    assert root.left.left.left.val == 4


def test_serialize_tree_of_none_is_empty():
    assert serialize_tree(None) == []


def test_serialize_tree_trims_trailing_nulls():
    assert serialize_tree(build_tree([1, 2, 3])) == [1, 2, 3]


@pytest.mark.parametrize(
    "values",
    [
        [1],
        [1, 2, 3],
        [3, 9, 20, None, None, 15, 7],
        [1, None, 2, None, 3],
        [5, 4, 7, 3, None, 2, None, -1, None, 9],
    ],
)
def test_tree_roundtrips(values):
    assert serialize_tree(build_tree(values)) == values


# -- linked lists ---------------------------------------------------------

def test_build_linked_list_of_empty_is_none():
    assert build_linked_list([]) is None


def test_build_linked_list_chains_nodes():
    head = build_linked_list([1, 2, 3])
    assert head.val == 1
    assert head.next.val == 2
    assert head.next.next.val == 3
    assert head.next.next.next is None


def test_serialize_linked_list_of_none_is_empty():
    assert serialize_linked_list(None) == []


@pytest.mark.parametrize("values", [[], [1], [1, 2, 3, 4, 5]])
def test_linked_list_roundtrips(values):
    assert serialize_linked_list(build_linked_list(values)) == values


# -- dispatch -------------------------------------------------------------

def test_decode_raw_passes_through_untouched():
    assert decode([1, 2, 3], "raw") == [1, 2, 3]
    assert decode("hello", "raw") == "hello"


def test_decode_grid_passes_through_untouched():
    assert decode([[1, 0], [0, 1]], "grid") == [[1, 0], [0, 1]]


def test_decode_tree_builds_a_node():
    assert isinstance(decode([1, 2], "tree"), TreeNode)


def test_decode_linked_list_builds_a_node():
    assert isinstance(decode([1, 2], "linked_list"), ListNode)


def test_encode_inverts_decode_for_trees():
    values = [3, 9, 20, None, None, 15, 7]
    assert encode(decode(values, "tree"), "tree") == values


def test_encode_inverts_decode_for_linked_lists():
    assert encode(decode([1, 2, 3], "linked_list"), "linked_list") == [1, 2, 3]


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown kind"):
        decode([1], "quaternion")


def test_a_codec_raising_keyerror_is_not_reported_as_an_unknown_kind(monkeypatch):
    """Wrapping the dispatch itself in `except KeyError` conflates 'no such
    kind' with 'the codec raised KeyError internally', which would send a
    future debugging session after entirely the wrong thing."""
    from algorhythm.codecs import leetcode_types

    def raises_keyerror(value):
        raise KeyError("something inside the codec")

    monkeypatch.setitem(leetcode_types._DECODERS, "tree", raises_keyerror)
    monkeypatch.setitem(leetcode_types._ENCODERS, "tree", raises_keyerror)

    with pytest.raises(KeyError):
        decode([1], "tree")
    with pytest.raises(KeyError):
        encode([1], "tree")


# -- graphs -----------------------------------------------------------------


def test_a_graph_round_trips_through_its_adjacency_lists():
    """Entry i lists the neighbours of the node whose val is i+1."""
    from algorhythm.codecs.leetcode_types import build_graph, serialize_graph

    square = [[2, 4], [1, 3], [2, 4], [1, 3]]
    assert serialize_graph(build_graph(square)) == square


def test_an_empty_graph_is_none_in_both_directions():
    from algorhythm.codecs.leetcode_types import build_graph, serialize_graph

    assert build_graph([]) is None
    assert serialize_graph(None) == []


def test_a_single_node_graph_has_no_neighbours():
    from algorhythm.codecs.leetcode_types import build_graph, serialize_graph

    assert serialize_graph(build_graph([[]])) == [[]]


def test_graph_serialization_orders_by_val_not_by_traversal():
    """A correct clone is built in whatever order the solution chose; only
    ordering by val makes it compare equal to the input."""
    from algorhythm.codecs.leetcode_types import Node, serialize_graph

    one, two, three = Node(1), Node(2), Node(3)
    one.neighbors = [two, three]
    two.neighbors = [one]
    three.neighbors = [one]
    assert serialize_graph(three) == [[2, 3], [1], [1]]


def test_graph_dispatches_through_decode_and_encode():
    from algorhythm.codecs.leetcode_types import decode, encode

    square = [[2, 4], [1, 3], [2, 4], [1, 3]]
    assert encode(decode(square, "graph"), "graph") == square


# -- linked lists with a cycle ----------------------------------------------


def test_a_cycle_is_built_from_the_pos_form():
    from algorhythm.codecs.leetcode_types import build_linked_list

    head = build_linked_list({"values": [3, 2, 0, -4], "pos": 1})
    tail = head.next.next.next
    assert tail.val == -4
    assert tail.next is head.next


def test_pos_minus_one_leaves_the_list_open():
    from algorhythm.codecs.leetcode_types import build_linked_list

    head = build_linked_list({"values": [1, 2], "pos": -1})
    assert head.next.next is None


def test_a_single_node_can_point_at_itself():
    from algorhythm.codecs.leetcode_types import build_linked_list

    head = build_linked_list({"values": [1], "pos": 0})
    assert head.next is head


def test_an_empty_cycle_form_is_still_none():
    from algorhythm.codecs.leetcode_types import build_linked_list

    assert build_linked_list({"values": [], "pos": -1}) is None


def test_the_plain_list_form_still_works():
    from algorhythm.codecs.leetcode_types import (
        build_linked_list,
        serialize_linked_list,
    )

    assert serialize_linked_list(build_linked_list([1, 2, 3])) == [1, 2, 3]
