from datetime import datetime, timezone

from algorhythm.catalog.models import ParamSpec, Problem
from algorhythm.oracle import candidate_args, generate_oracle_cases, perturbations


def problem(entry_point="total", params=None, return_kind="raw") -> Problem:
    return Problem(
        slug="fixture",
        number=1,
        title="Fixture",
        difficulty="Easy",
        topics=[],
        companies=[],
        url="",
        statement_md="",
        constraints=[],
        examples=[],
        params=params or [ParamSpec("nums")],
        return_kind=return_kind,
        entry_point=entry_point,
        fetched_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )


REFERENCE = """
class Solution:
    def total(self, nums):
        return sum(nums)
"""

REFERENCE_TWO_ARGS = """
class Solution:
    def total(self, nums, k):
        return sum(nums) * k
"""


# -- perturbation ---------------------------------------------------------

def test_int_list_perturbations_include_empty_and_singleton():
    variants = perturbations([1, 2, 3], "raw")
    assert [] in variants
    assert any(len(v) == 1 for v in variants)


def test_int_list_perturbations_include_duplicates():
    variants = perturbations([1, 2, 3], "raw")
    assert any(len(set(v)) == 1 and len(v) > 1 for v in variants)


def test_int_list_perturbations_include_negatives():
    variants = perturbations([1, 2, 3], "raw")
    assert any(any(x < 0 for x in v) for v in variants)


def test_string_perturbations_include_empty_and_single_char():
    variants = perturbations("hello", "raw")
    assert "" in variants
    assert any(len(v) == 1 for v in variants)


def test_int_perturbations_span_zero_and_negative():
    variants = perturbations(5, "raw")
    assert 0 in variants
    assert any(v < 0 for v in variants)


def test_tree_perturbations_include_empty_and_single_node():
    variants = perturbations([3, 9, 20, None, None, 15, 7], "tree")
    assert [] in variants
    assert [1] in variants


def test_tree_perturbations_include_a_skewed_chain():
    """Skewed trees are where naive index-arithmetic solutions break."""
    variants = perturbations([1, 2, 3], "tree")
    assert any(None in v for v in variants if isinstance(v, list) and len(v) > 2)


def test_linked_list_perturbations_include_empty_and_single():
    variants = perturbations([1, 2, 3], "linked_list")
    assert [] in variants
    assert [1] in variants


def test_grid_perturbations_include_single_cell():
    variants = perturbations([[1, 0], [0, 1]], "grid")
    assert [[1]] in variants


def test_perturbations_never_include_the_original():
    assert [1, 2, 3] not in perturbations([1, 2, 3], "raw")


# -- candidate assembly ---------------------------------------------------

def test_candidates_vary_one_parameter_at_a_time():
    """Cartesian product would explode; one-at-a-time keeps it linear."""
    p = problem(params=[ParamSpec("nums"), ParamSpec("k")])
    seed = {"nums": [1, 2, 3], "k": 2}
    candidates = candidate_args(p, seed)
    for candidate in candidates:
        differing = [name for name in seed if candidate[name] != seed[name]]
        assert len(differing) == 1


def test_candidates_are_deduplicated():
    p = problem(params=[ParamSpec("nums")])
    candidates = candidate_args(p, {"nums": [1, 2, 3]})
    # Candidate values are lists (unhashable), so compare via string
    # representation rather than putting the raw items in a set.
    seen = [str(sorted(c.items(), key=str)) for c in candidates]
    assert len(seen) == len(set(seen))


# -- generation -----------------------------------------------------------

def test_generated_cases_take_expectations_from_the_reference(tmp_path):
    reference = tmp_path / "reference.py"
    reference.write_text(REFERENCE)
    cases = generate_oracle_cases(problem(), reference, {"nums": [1, 2, 3]})
    assert cases
    for case in cases:
        assert case.expected == sum(case.args["nums"])


def test_generated_cases_are_tagged_as_oracle(tmp_path):
    reference = tmp_path / "reference.py"
    reference.write_text(REFERENCE)
    cases = generate_oracle_cases(problem(), reference, {"nums": [1, 2, 3]})
    assert all(c.source == "oracle" for c in cases)


def test_generated_case_ids_are_unique(tmp_path):
    reference = tmp_path / "reference.py"
    reference.write_text(REFERENCE)
    cases = generate_oracle_cases(problem(), reference, {"nums": [1, 2, 3]})
    assert len({c.id for c in cases}) == len(cases)


def test_inputs_the_reference_rejects_are_dropped(tmp_path):
    """A reference that raises on empty input means empty is out of contract,
    so that candidate must not become a test case."""
    reference = tmp_path / "reference.py"
    reference.write_text(
        """
class Solution:
    def total(self, nums):
        if not nums:
            raise ValueError("out of contract")
        return sum(nums)
"""
    )
    cases = generate_oracle_cases(problem(), reference, {"nums": [1, 2, 3]})
    assert all(c.args["nums"] != [] for c in cases)


def test_multi_parameter_problems_work(tmp_path):
    reference = tmp_path / "reference.py"
    reference.write_text(REFERENCE_TWO_ARGS)
    p = problem(params=[ParamSpec("nums"), ParamSpec("k")])
    cases = generate_oracle_cases(p, reference, {"nums": [1, 2], "k": 3})
    assert cases
    for case in cases:
        assert case.expected == sum(case.args["nums"]) * case.args["k"]


def test_a_broken_reference_yields_no_cases_rather_than_raising(tmp_path):
    reference = tmp_path / "reference.py"
    reference.write_text("class Solution:\n    def total(self nums):\n")
    assert generate_oracle_cases(problem(), reference, {"nums": [1, 2, 3]}) == []


# -- budget: truncation must not starve valid candidates ------------------

REFERENCE_K_ONLY_NEGATIVE = """
class Solution:
    def total(self, nums, k):
        if k not in (-1, -2):
            raise ValueError("out of contract")
        return sum(nums) * k
"""


def test_valid_candidates_past_the_old_truncation_point_are_still_found(tmp_path):
    """Regression: candidates used to be capped to 8 before the reference
    ever ran. With `nums` a 7-element list (whose perturbations alone fill
    most of that cap) and only k in {-1, -2} in contract, the in-contract
    candidates used to fall past the cut and never even reach the
    reference — yielding zero cases despite valid ones existing."""
    reference = tmp_path / "reference.py"
    reference.write_text(REFERENCE_K_ONLY_NEGATIVE)
    p = problem(params=[ParamSpec("nums"), ParamSpec("k")])
    cases = generate_oracle_cases(p, reference, {"nums": [1, 2, 3, 4, 5, 6, 7], "k": 2})
    assert cases
    assert all(c.args["k"] in (-1, -2) for c in cases)


def test_candidates_round_robin_across_parameters():
    """Parameter-major ordering would let the first parameter's variants
    consume the whole truncation budget, leaving the second parameter with
    no coverage at all. Round-robin ensures it shows up early."""
    p = problem(params=[ParamSpec("nums"), ParamSpec("k")])
    seed = {"nums": [1, 2, 3, 4, 5, 6, 7], "k": 2}
    candidates = candidate_args(p, seed)
    assert any(c["k"] != seed["k"] for c in candidates[:2])


def test_generated_case_ids_stay_contiguous_when_candidates_are_rejected(tmp_path):
    reference = tmp_path / "reference.py"
    reference.write_text(
        """
class Solution:
    def total(self, nums):
        if not nums:
            raise ValueError("out of contract")
        return sum(nums)
"""
    )
    cases = generate_oracle_cases(problem(), reference, {"nums": [1, 2, 3]})
    assert [c.id for c in cases] == [f"oracle-{i + 1}" for i in range(len(cases))]


def test_generated_cases_are_capped_even_with_many_valid_candidates(tmp_path):
    reference = tmp_path / "reference.py"
    reference.write_text(REFERENCE_TWO_ARGS)
    p = problem(params=[ParamSpec("nums"), ParamSpec("k")])
    cases = generate_oracle_cases(p, reference, {"nums": [1, 2, 3, 4, 5, 6, 7], "k": 2})
    assert len(cases) == 8


def test_grid_perturbations_keep_the_grid_s_own_cell_type():
    """A hardcoded `[[1]]` is an int grid.

    number-of-islands takes a grid of "1"/"0" strings, whose C++ signature is
    `vector<vector<char>>&`. An int-valued variant makes the generated
    harness declare `vector<vector<int>>`, which does not bind — so the
    problem stops compiling in C++ entirely.
    """
    from algorhythm.oracle import perturbations

    grid = [["1", "1", "0"], ["0", "1", "0"]]
    for variant in perturbations(grid, "grid"):
        cells = [cell for row in variant for cell in row]
        assert all(isinstance(cell, str) for cell in cells), variant


def test_grid_perturbations_still_vary_an_int_grid():
    from algorhythm.oracle import perturbations

    variants = perturbations([[1, 0], [0, 1]], "grid")
    assert variants
    for variant in variants:
        cells = [cell for row in variant for cell in row]
        assert all(isinstance(cell, int) for cell in cells), variant


def test_an_empty_grid_has_no_perturbations():
    """Nothing to borrow a cell type from, so guessing one is not allowed."""
    from algorhythm.oracle import perturbations

    assert perturbations([], "grid") == []
