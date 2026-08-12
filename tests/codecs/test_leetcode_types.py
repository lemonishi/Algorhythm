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
