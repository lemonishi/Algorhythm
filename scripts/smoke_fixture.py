"""Seed two hand-written problems, so the loop can be exercised offline.

`algorhythm seed` is the real path, but it calls LeetCode's API. This module
carries two problems as literals instead and pushes them through the same
`seed_problems` machinery — oracle generation included — so a smoke test
covers everything except the network fetch itself.

The two are chosen to hit different code paths: two-sum has scalar and list
parameters, maximum-depth-of-binary-tree has a `tree` parameter, which is
what exercises node deserialization in both runners and the ASCII drawing
in the statement pane.

    ALGORHYTHM_HOME=/tmp/algorhythm-smoke python scripts/smoke_fixture.py
"""

from __future__ import annotations

from datetime import datetime, timezone

from algorhythm.catalog.models import Example, ParamSpec, Problem, TestCase
from algorhythm.seed import seed_problems

TWO_SUM = Problem(
    slug="two-sum",
    number=1,
    title="Two Sum",
    difficulty="Easy",
    topics=["Array", "Hash Table"],
    companies=[],
    url="https://leetcode.com/problems/two-sum/",
    statement_md=(
        "Given an array of integers `nums` and an integer `target`, return "
        "*indices of the two numbers such that they add up to `target`*.\n\n"
        "You may assume that each input would have **exactly one solution**, "
        "and you may not use the same element twice.\n\n"
        "You can return the answer in any order."
    ),
    constraints=[
        "2 <= nums.length <= 10^4",
        "-10^9 <= nums[i] <= 10^9",
        "-10^9 <= target <= 10^9",
        "Only one valid answer exists.",
    ],
    examples=[
        Example(
            input_text="nums = [2,7,11,15], target = 9",
            output_text="[0,1]",
            explanation="Because nums[0] + nums[1] == 9, we return [0, 1].",
        ),
        Example(input_text="nums = [3,2,4], target = 6", output_text="[1,2]"),
    ],
    params=[ParamSpec("nums"), ParamSpec("target")],
    return_kind="raw",
    entry_point="twoSum",
    fetched_at=datetime.now(tz=timezone.utc),
    stubs={
        "python": (
            "class Solution:\n"
            "    def twoSum(self, nums: List[int], target: int) -> List[int]:\n"
            "        "
        ),
        "cpp": (
            "class Solution {\n"
            "public:\n"
            "    vector<int> twoSum(vector<int>& nums, int target) {\n"
            "        \n"
            "    }\n"
            "};\n"
        ),
    },
    example_cases=[
        TestCase(
            id="example-1",
            args={"nums": [2, 7, 11, 15], "target": 9},
            expected=[0, 1],
            source="example",
        ),
        TestCase(
            id="example-2",
            args={"nums": [3, 2, 4], "target": 6},
            expected=[1, 2],
            source="example",
        ),
    ],
)

MAX_DEPTH = Problem(
    slug="maximum-depth-of-binary-tree",
    number=104,
    title="Maximum Depth of Binary Tree",
    difficulty="Easy",
    topics=["Tree", "Depth-First Search", "Binary Tree"],
    companies=[],
    url="https://leetcode.com/problems/maximum-depth-of-binary-tree/",
    statement_md=(
        "Given the `root` of a binary tree, return *its maximum depth*.\n\n"
        "A binary tree's **maximum depth** is the number of nodes along the "
        "longest path from the root node down to the farthest leaf node."
    ),
    constraints=[
        "The number of nodes in the tree is in the range [0, 10^4].",
        "-100 <= Node.val <= 100",
    ],
    examples=[
        Example(input_text="root = [3,9,20,null,null,15,7]", output_text="3"),
        Example(input_text="root = [1,null,2]", output_text="2"),
    ],
    params=[ParamSpec("root", kind="tree")],
    return_kind="raw",
    entry_point="maxDepth",
    fetched_at=datetime.now(tz=timezone.utc),
    stubs={
        "python": (
            "# Definition for a binary tree node.\n"
            "# class TreeNode:\n"
            "#     def __init__(self, val=0, left=None, right=None):\n"
            "#         self.val = val\n"
            "#         self.left = left\n"
            "#         self.right = right\n"
            "class Solution:\n"
            "    def maxDepth(self, root: Optional[TreeNode]) -> int:\n"
            "        "
        ),
        "cpp": (
            "class Solution {\n"
            "public:\n"
            "    int maxDepth(TreeNode* root) {\n"
            "        \n"
            "    }\n"
            "};\n"
        ),
    },
    example_cases=[
        TestCase(
            id="example-1",
            args={"root": [3, 9, 20, None, None, 15, 7]},
            expected=3,
            source="example",
        ),
        TestCase(
            id="example-2", args={"root": [1, None, 2]}, expected=2, source="example"
        ),
    ],
)

PROBLEMS = {problem.slug: problem for problem in (TWO_SUM, MAX_DEPTH)}

# Stands in for what `fetch_reference_from_github` would return. These are
# the solutions the reviewer compares your answer against, and the oracle
# derives every non-example expected value by running the Python one — so a
# wrong reference here yields wrong tests, silently.
REFERENCES = {
    ("two-sum", "python"): (
        "class Solution:\n"
        "    def twoSum(self, nums: List[int], target: int) -> List[int]:\n"
        "        seen = {}\n"
        "        for index, value in enumerate(nums):\n"
        "            if target - value in seen:\n"
        "                return [seen[target - value], index]\n"
        "            seen[value] = index\n"
        "        return []\n"
    ),
    ("two-sum", "cpp"): (
        "class Solution {\n"
        "public:\n"
        "    vector<int> twoSum(vector<int>& nums, int target) {\n"
        "        unordered_map<int, int> seen;\n"
        "        for (int i = 0; i < (int)nums.size(); i++) {\n"
        "            auto it = seen.find(target - nums[i]);\n"
        "            if (it != seen.end()) return {it->second, i};\n"
        "            seen[nums[i]] = i;\n"
        "        }\n"
        "        return {};\n"
        "    }\n"
        "};\n"
    ),
    ("maximum-depth-of-binary-tree", "python"): (
        "class Solution:\n"
        "    def maxDepth(self, root: Optional[TreeNode]) -> int:\n"
        "        if root is None:\n"
        "            return 0\n"
        "        return 1 + max(self.maxDepth(root.left), self.maxDepth(root.right))\n"
    ),
    ("maximum-depth-of-binary-tree", "cpp"): (
        "class Solution {\n"
        "public:\n"
        "    int maxDepth(TreeNode* root) {\n"
        "        if (!root) return 0;\n"
        "        return 1 + max(maxDepth(root->left), maxDepth(root->right));\n"
        "    }\n"
        "};\n"
    ),
}


def fetch(slug: str) -> Problem:
    if slug not in PROBLEMS:
        raise KeyError(f"no fixture for {slug!r}")
    return PROBLEMS[slug]


def fetch_reference(number: int, slug: str, language: str) -> str | None:
    return REFERENCES.get((slug, language))


def main() -> int:
    from algorhythm import config

    report = seed_problems(
        list(PROBLEMS), fetch=fetch, fetch_reference=fetch_reference
    )
    print(report.render())
    print(f"\nlibrary: {config.problems_dir()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
