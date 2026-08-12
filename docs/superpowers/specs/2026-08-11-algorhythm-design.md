# algorhythm — Design Spec

**Date:** 2026-08-11
**Status:** Approved, pre-implementation
**Scope of this document:** v1 in full detail. v2 and v3 are named with enough context to plan against, but their designs are deliberately deferred.

---

## 1. Purpose

`algorhythm` is a terminal application for preparing for LeetCode-style technical interviews using spaced repetition.

The premise: solving a DSA problem once teaches you little, because the skill being tested is *pattern recall under time pressure*. Existing tools either schedule reps without evaluating quality (Anki with hand-made cards) or evaluate quality without scheduling (LeetCode itself). This tool does both, and adds the thing neither provides — an assessment of **how far your solution was from the recommended one**, which is the signal worth scheduling against.

**Primary user:** the author, who is also the only user for the foreseeable future. Every design decision assumes a single local user on one machine. Nothing is multi-tenant, networked, or hosted.

**Non-goals for v1:** competitive programming, non-DSA interview prep (system design, behavioral), collaborative or social features, mobile, web UI, hosting.

---

## 2. The core loop

```
algorhythm review
  → scheduler returns problems due today (capped)
  → TUI shows the queue; user picks one
  → nvim opens: statement in a read-only left split, solution on the right
  → :w              runs the local test suite, results in a bottom split
  → :Review         local LLM reviews the solution against the reference
  → quit nvim
  → TUI shows the review with a proposed grade; user confirms or overrides
  → scheduler computes the next interval; store persists
```

One rep is expected to take 20–45 minutes of user time and under 30 seconds of tool time.

---

## 3. Key decisions and their rationale

Recorded so a future session does not relitigate them.

| Decision | Rationale |
|---|---|
| **Terminal, not web** | The user solves in nvim. Every context switch out of the terminal is friction on a loop that must be run daily to work at all. |
| **Statement rendered fully in-terminal, not linked out** | Detail parity with LeetCode/NeetCode was an explicit requirement. Linking out reintroduces the browser context switch. |
| **Content fetched from LeetCode, not authored** | Accuracy. Hand-writing or LLM-generating 150 statements from recall produces subtly wrong constraints and examples, which corrupt reviews permanently. |
| **Reference solutions from `neetcode-gh/leetcode`** | Human-written and reviewed, MIT-licensed, available in both target languages, and aligned with the NeetCode 150 seed set. |
| **Reference solution is fed into every review prompt** | This is the load-bearing decision for local-model viability. It converts "recall the optimal approach for problem N" (recall-heavy, where a 7B model is weakest) into "compare these two solutions" (comparison, where it is adequate). |
| **Local model (Ollama), not a cloud API** | User preference. Costs no money, works offline, keeps solutions private. Accepted trade: measurably weaker reviews. |
| **`qwen2.5-coder:7b` specifically** | Largest code-specialised model that fits 8 GB unified memory at 4-bit quantisation (~4.7 GB). 14B would thrash. |
| **SM-2, not FSRS** | FSRS is better but needs hundreds to thousands of reviews before its parameters beat defaults. At ~5 reps/day that is years away. SM-2 is good cold. The review log is captured in FSRS-ready shape so the switch stays available. |
| **SRS is deterministic code, not an LLM agent** | Scheduling is arithmetic. An LLM would make it non-deterministic, unauditable, untestable, capable of hallucinating dates, and would add 5–20 s of inference to do multiplication. |
| **Python, not Go** | Reversed mid-design. Go won on startup latency (~10 ms vs ~400 ms), but the 7B model dominates rep latency by 10–40×, and the v2/v3 roadmap (LangGraph) needs the Python ecosystem. Two runtimes for a solo tool is a worse permanent cost than 400 ms. |
| **No LangChain** | Audited capability-by-capability: provider abstraction, prompt templates, output parsing, chains, retrieval, memory, document loaders, tool abstractions, tracing — zero apply. The v1 LLM surface is one HTTP POST. |
| **LangGraph deferred to v2** | A single stateless call is not a graph. Adopting it now means building scaffolding around a single node — an empty abstraction that makes edits harder and gets redesigned anyway once the real multi-node shape is known. |
| **Content on disk, state in SQLite** | Content is read-mostly, benefits from being greppable, diffable, git-trackable, and fixable in an editor when a fetch comes out mangled. Scheduling state is write-heavy relational data wanting transactions and `WHERE due_at <= now()`. |
| **SQLite, not PostgreSQL** | ~150 problem rows and a few thousand review rows. Postgres would add a daemon, ~50–100 MB idle RAM competing with a 4.7 GB model, and a failure mode where the CLI cannot start. |

---

## 4. Architecture

```
algorhythm/
  cli.py                  Typer entry point: review, add, list, stats
  catalog/
    models.py             Problem, Example, TestCase dataclasses
    fetch.py              LeetCode GraphQL client
    render.py             HTML → markdown; ASCII rendering for trees/grids/lists
    store.py              load/save problem directories
  scheduler/
    sm2.py                the algorithm — pure functions, no I/O
    queue.py              due queue, daily cap, rollover
  store/
    db.py                 connection, schema migrations
    repository.py         the ONLY module that writes SQL
  runner/
    harness.py            orchestration: batching, oracle comparison, timeouts
    python_runner.py      in-process or subprocess execution
    cpp_runner.py         content-hashed compile cache
  reviewer/
    protocol.py           Reviewer Protocol — the seam for v2/v3 and model swaps
    ollama.py             the v1 implementation
    prompt.py             prompt construction
  editor/
    session.py            nvim workspace setup and launch
    lua/algorhythm.lua    splits, :w hook, :Review command
  tui/
    app.py                Textual application
```

**Boundaries.** Each package has one responsibility and communicates through small typed interfaces. Two seams matter most:

- `store/repository.py` is the only module containing SQL. A future migration off SQLite touches one file.
- `reviewer/protocol.py` defines a `Reviewer` Protocol. Swapping Ollama for Claude, or adding the v2 LangGraph hint agent, means a new implementation — not a refactor.

**Dependencies:** `typer` (CLI), `textual` (TUI), `httpx` (Ollama + LeetCode), `sqlite3` (stdlib). Anything heavy is lazy-imported so `algorhythm review` stays responsive.

---

## 5. Data

### 5.1 Problem content on disk

One directory per problem under `~/.local/share/algorhythm/problems/`:

```
0102-binary-tree-level-order-traversal/
  meta.json         slug, number, title, difficulty, topic tags, company tags,
                    leetcode url, fetched_at, company_tags_source, company_tags_asof
  statement.md      converted from LeetCode's statement HTML
  examples.json     inputs, expected outputs, explanations
  tests.json        example cases + oracle-derived edge cases
  reference.py      reference.cpp
  stub.py           stub.cpp    (from LeetCode codeSnippets — real signatures)
```

Attempts are written to `~/.local/share/algorhythm/attempts/<slug>/<timestamp>.<ext>` so a re-rep can open your previous solution folded beneath the fresh stub.

### 5.2 SQLite schema

```sql
CREATE TABLE schedule (
  slug              TEXT PRIMARY KEY,
  due_at            TEXT NOT NULL,       -- ISO 8601
  interval_days     REAL NOT NULL,
  ease              REAL NOT NULL,       -- starts 2.5, floor 1.3
  reps              INTEGER NOT NULL,
  lapses            INTEGER NOT NULL,
  last_grade        TEXT,                -- again | hard | good | easy
  last_reviewed_at  TEXT
);

CREATE TABLE reviews (
  id                INTEGER PRIMARY KEY,
  slug              TEXT NOT NULL,
  reviewed_at       TEXT NOT NULL,
  grade             TEXT NOT NULL,
  proposed_grade    TEXT,                -- what the model suggested
  interval_before   REAL, interval_after REAL,
  ease_before       REAL, ease_after     REAL,
  elapsed_ms        INTEGER,             -- time from open to grade
  tests_passed      INTEGER, tests_total INTEGER,
  language          TEXT,                -- python | cpp
  model             TEXT,                -- e.g. qwen2.5-coder:7b
  review_text       TEXT
);

CREATE TABLE attempts (
  id        INTEGER PRIMARY KEY,
  slug      TEXT NOT NULL,
  saved_at  TEXT NOT NULL,
  language  TEXT NOT NULL,
  source    TEXT NOT NULL
);
```

`reviews` is deliberately over-captured: every field FSRS would need to train on is recorded from the first rep, even though SM-2 uses only a few. This is cheap now and is the only thing that makes a future FSRS migration possible.

---

## 6. Content acquisition

### 6.1 Fetching from LeetCode

`algorhythm add <slug-or-url>` queries `https://leetcode.com/graphql` — the endpoint LeetCode's own frontend uses — for the `question` object by `titleSlug`. No authentication required for public problems.

**Available:** title, question number, statement HTML, worked examples, constraints, difficulty, topic tags, hints, and `codeSnippets` (per-language function signatures, used verbatim as our stubs).

**Not available:** the reference solution, the hidden judge test suite, and company tags — all LeetCode Premium.

The same code path seeds the initial library: run the fetcher once over the NeetCode 150 slug list and commit the results.

### 6.2 Reference solutions

Sourced from the public `neetcode-gh/leetcode` repository (Python and C++, human-written, MIT-licensed), which covers the NeetCode 150 seed set. Problems added later that are not on that list need a reference written by hand or by a strong model — explicitly **not** by the local 7B, since a wrong reference silently corrupts every future review of that problem.

### 6.3 Company tags

Imported best-effort from public mirrors of LeetCode Premium data. These are scraped snapshots of varying age and accuracy. `meta.json` records `company_tags_source` and `company_tags_asof` so a stale tag never presents as authoritative, and the UI marks them accordingly.

### 6.4 Images

LeetCode statements include diagrams. Handling, in order of preference:

1. **ASCII rendering from the input data.** Trees, grids, and linked lists — the large majority of diagram-bearing problems — are reconstructible from the example input array (`root = [3,9,20,null,null,15,7]` renders as an ASCII tree). Deterministic, and clearer in a terminal than the original.
2. **Text description** for genuinely pictorial problems (e.g. Trapping Rain Water's bar chart), stored at fetch time.

Images are referenced by URL in `meta.json`, never copied into the repository.

---

## 7. Test execution

### 7.1 What the tests contain

- **Example cases** from LeetCode's `exampleTestcases`, with the stated expected outputs.
- **Edge cases** — empty, single element, duplicates, maximum constraint, negatives — whose expected outputs are produced by **running the reference solution as an oracle**. No hand-authored expectations.

This is a NeetCode-grade suite, not a LeetCode-judge-grade one. A wrong solution can still pass. That is an accepted limitation: the tests exist to catch obvious breakage fast and to give the reviewer grounded facts about correctness, not to be the final arbiter.

### 7.2 Performance

Target: ~50 ms for a Python run, ~20 ms for a cached C++ run.

| Technique | Effect |
|---|---|
| **Content-hashed C++ binary cache** — key on the hash of the source | 1–3 s → ~0 ms on re-runs. Largest single win. |
| **`-O0` for test builds** — inputs are tiny; runtime speed is irrelevant | ~3× faster first compile |
| **Batch all cases into one process invocation** per language | ~10× at a dozen cases |
| **Parallel case execution** via `concurrent.futures` | ~cores× on slow cases; subprocess-bound so the GIL is irrelevant |
| **Per-case timeout** (default 5 s) | An infinite loop is killed and reported as `TIMEOUT` rather than hanging the CLI |

---

## 8. The reviewer

### 8.1 Model and transport

`qwen2.5-coder:7b` via Ollama at `http://localhost:11434`. A single `httpx` POST per review, streamed. Ollama's `format` parameter takes a JSON schema, so the response comes back structured:

```json
{
  "review": "<prose>",
  "proposed_grade": "again | hard | good | easy",
  "grade_reason": "<one line>"
}
```

No output-parsing layer is needed.

### 8.2 Prompt contents

Grounding is what makes a 7B model viable here. Every prompt carries:

- The problem statement and constraints
- **The reference solution** in the user's chosen language
- The user's submitted solution
- Concrete test results (which cases passed, which failed, on what input)

The review is **holistic prose**, not a fixed rubric — it should say what is actually worth saying about that solution, covering complexity or edge cases when those are the interesting part and skipping them when they are not. The system prompt is stable across all reviews, which keeps it cacheable.

### 8.3 Known limitation

This is the weakest component of v1 and is expected to be. A 7B model will occasionally be confidently wrong about approach quality. Mitigations are the grounding above, the fact that correctness comes from the test runner rather than the model, and the fact that the user confirms every grade. The `Reviewer` Protocol means swapping in a stronger model later is a contained change.

---

## 9. Scheduling

SM-2, tuned for the fact that a card here costs 20–45 minutes rather than 5 seconds.

| Parameter | Anki default | Here | Why |
|---|---|---|---|
| First interval after `good` | 1 day | **3 days** | A 1-day queue is unsustainable at 20 min/problem |
| Learning steps | minutes | **none** | You cannot re-solve a problem in 10 minutes |
| `again` | reset to ~1 day | **max(1, prev × 0.3)** days, ease − 0.20 | A lapse costs 20 minutes; a full reset is disproportionate |
| `hard` | × 1.2 | × 1.2, ease − 0.15 | unchanged |
| `good` | × ease | × ease | unchanged |
| `easy` | × ease × 1.3 | × ease × 1.3, ease + 0.15 | unchanged |
| Daily cap | none | **5, overflow rolls forward** | Hard ceiling on daily commitment |

Ease starts at 2.5 and floors at 1.3. Overflow is ordered oldest-due-first.

**Grading is Anki's four buttons, with the model pre-selecting one.** The model sees the code quality; the user knows whether the pattern actually came to them or whether they flailed into it. Neither has the full picture, so the model drafts and the user signs off with a keypress. This also counteracts the known drift in pure self-grading.

---

## 10. User interface

### 10.1 Queue and grading — Textual TUI

Shows the due queue and, after a rep, the review text with the proposed grade highlighted. Enter accepts; arrows override.

### 10.2 The rep — nvim

The CLI prepares a scratch workspace and launches nvim with a small Lua module:

```
┌─ 102. Level Order ─────┬─ solution.py ─────────┐
│ ● Medium  Trees·BFS    │ class Solution:       │
│ ⌘ Amazon Meta Google   │   def levelOrder(     │
│ 3rd rep · 12d ago      │     self,             │
│                        │     root: TreeNode    │
│ Given the root of a    │   ) -> List[List[int]]:│
│ binary tree, return    │     if not root:      │
│ the level order tra-   │       return []       │
│ versal of its nodes'   │     q = deque([root]) │
│ values.                │     █                 │
│                        │                       │
│ Example 1:             │                       │
│     3                  │                       │
│    / \                 │                       │
│   9  20                │                       │
│      / \               │                       │
│     15  7              │                       │
│  In:  [3,9,20,null,    │                       │
│        null,15,7]      │                       │
│  Out: [[3],[9,20],     │                       │
│        [15,7]]         │                       │
│                        │                       │
│ Constraints:           │                       │
│  • [0, 2000] nodes     │                       │
│  • -1000 <= val <= 1000│                       │
├────────────────────────┴───────────────────────┤
│ :w → run tests   :Review → grade               │
└────────────────────────────────────────────────┘
```

Left split is the rendered statement, read-only. Right split is `solution.py` or `solution.cpp`, seeded with the LeetCode stub (or the previous attempt on a re-rep). `:w` runs the tests into a bottom split. `:Review` streams the model's review into a buffer.

### 10.3 Language selection

A rep is solved in exactly one language. Resolution order:

1. `--lang python|cpp` on the `review` command, if given.
2. The language used on the previous rep of that problem, if any (recorded in `reviews.language`).
3. The configured default (`python`).

Language is a property of the attempt, not the problem — the same problem may be solved in Python on one rep and C++ on the next, and both attempts are retained. Scheduling is per-problem and language-agnostic: solving in C++ does not create a separate card.

---

## 11. Failure modes

**Governing rule: nothing blocks the SRS loop.** A rep can always be completed and graded.

| Failure | Behaviour |
|---|---|
| Ollama not running | Tests still run; review skipped with a notice; user self-grades |
| LeetCode fetch fails or schema changed | Clear error; **no partial problem directory written** |
| C++ compile error | Surfaced as test output carrying the compiler message; not a crash |
| Solution infinite-loops | Per-case timeout kills it; reported as `TIMEOUT` |
| Reference solution missing | Review runs without comparison and says so explicitly |
| nvim exits without saving | Rep abandoned; nothing written to the database |
| Model returns malformed output | Review shown raw; no grade proposed; user grades manually |

---

## 12. Testing strategy

| Package | Approach |
|---|---|
| `scheduler` | Table-driven tests over grade sequences asserting exact resulting intervals. **Highest priority** — a silent bug here costs months of wrong scheduling with no visible symptom. |
| `runner` | Golden tests against fixture problems with known-correct and known-broken solutions, including a deliberate infinite loop to exercise the timeout. |
| `catalog` | Parses **recorded** LeetCode GraphQL responses from disk. Tests never hit the network and do not break when LeetCode changes. Includes ASCII-rendering assertions. |
| `reviewer` | Mock Ollama; asserts prompt construction and structured-output handling, including the malformed-response path. |
| `store` | In-memory SQLite. |

`scheduler` and `runner` should be built test-first — correctness is subtle and regressions are silent.

---

## 13. Known risks

| Risk | Assessment |
|---|---|
| **Review quality at 7B** | The weakest part of v1, by design. Mitigated by grounding and by the fact that correctness comes from tests. If unacceptable in practice, the `Reviewer` seam makes a stronger model a contained swap. |
| **LeetCode ToS** | Their terms prohibit automated access. Accepted for a personal local tool. Would need reconsidering before any public distribution. |
| **LeetCode statement copyright** | Cached statements are copyrighted. Fine locally; a blocker to open-sourcing the repository with content included. Content directory should be gitignored if the repo ever goes public. |
| **GraphQL schema drift** | The fetcher will break when LeetCode changes its schema. Contained to `catalog/fetch.py` and detected by recorded-response tests only after the fact. |
| **Company tag staleness** | Provenance recorded in `meta.json` and surfaced in the UI. Never presented as authoritative. |

---

## 14. Roadmap beyond v1

Deferred deliberately. Both are genuine LangGraph shapes — cycles, state persisting across model calls, and interrupts waiting on the user — which is the threshold for adopting it. **LangGraph would be used standalone; LangChain remains excluded.**

- **v2 — Progressive hint escalation.** Graduated nudges when stuck: smallest useful hint → retry → still failing → larger hint → approach → code. State is hint level plus attempt history. Works acceptably on the local 7B since each hint is short.
- **v3 — Mock interview mode.** Multi-turn simulated interview: clarifying questions, approach narration, interviewer pushback, follow-ups. Wants checkpointing so a session can be resumed. Likely needs a cloud model — ten turns of growing context on a 7B in 8 GB will degrade. Budget roughly 4¢ per interview on Claude Opus 5.

---

## 15. Environment assumptions

- macOS on Apple Silicon (M2, 8 GB unified memory)
- Ollama installed; `qwen2.5-coder:7b` pulled (~4.7 GB)
- nvim available on `PATH`
- Python 3.11+
- A C++ compiler (`clang++`) on `PATH`
- Network access required only for `add`; the daily loop is fully offline
