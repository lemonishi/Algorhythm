# algorhythm

Spaced repetition for DSA interview prep. Problems come from LeetCode,
you solve them in nvim, a local model tells you how far your answer is
from the reference, and an SM-2 scheduler decides when you see each one
again.

Everything runs on your machine. The only network calls are seeding the
library and, if you want them, model downloads.

---

## Setup

Prerequisites: **Python 3.11+**, **nvim**, **ollama**, and **clang++** if
you want to solve in C++ (macOS ships it with the Xcode command line
tools).

```bash
pip install -e .                 # from the repo root
ollama pull qwen2.5-coder:7b     # the reviewer model, ~4.7 GB
algorhythm seed                  # populate the library
```

`algorhythm seed` calls LeetCode's public GraphQL API, which is against
their terms of service. It's your call whether to run it. If you'd rather
not, `python3 scripts/smoke_fixture.py` seeds two problems offline and
everything below works the same way.

---

## Daily use

```bash
algorhythm review
```

That's the whole app. What happens, in order:

1. **Queue screen** — today's problems. `j` / `k` to move, `l` or `Enter`
   to open one, `h` or `Esc` to quit. Arrows work too.
2. **nvim opens** with three panes: statement on the left and your
   solution on the right, equal width, with results along the bottom.
   Opening the review pane keeps those two balanced.
3. **`:w`** runs the tests and fills the results pane. Save as often as
   you like.
4. **`:Review`** asks the local model to compare your solution against
   the reference. Opens a fourth pane.
5. **`:qa`** ends the rep.
6. **Grade screen** — the model pre-selects a grade. `h` / `l` (or the
   arrows) to change it, `Enter` to commit and schedule the next
   repetition, `Esc` to abandon the rep.

Nothing is written to the database until you grade. `Esc` on the grade
screen leaves no trace — no attempt, no schedule change.

### Inside nvim

| Key | Does |
|---|---|
| `:w` | Run the tests |
| `:Review` | Ask the model for a review |
| `:qa` | End the rep, go to grading |
| `Ctrl-w` + `hjkl` | Move between panes |

The statement and results panes are read-only.

---

## Commands

### `algorhythm review`

```bash
algorhythm review --limit 10        # up to 10 problems today (default 5)
algorhythm review --new 0           # review only, introduce nothing new (default 2)
algorhythm review --lang cpp        # do every rep this session in C++
```

`--limit` caps the whole queue. `--new` caps only *unseen* problems, and
due reviews are filled first — so on a heavy review day nothing new is
introduced. That's deliberate: retention beats coverage, and every new
problem you take on today becomes review load for weeks.

The two are independent, which catches people out: on a library where
everything is still unseen, raising `--limit` alone changes nothing,
because `--new` is what's binding. Raise both:

```bash
algorhythm review --limit 10 --new 10
```

When that is what shortened your queue, the queue screen says so and
names the flag.

Without `--lang`, each problem uses whatever language you last solved it
in, defaulting to Python.

### Practising one topic

```bash
algorhythm topics                              # what the library carries
algorhythm review --topic graph                # graphs only
algorhythm review -t tree -t "linked list"     # either, not both
```

Matching is partial and case-insensitive, so `graph` finds LeetCode's
`Graph Theory` and `hash-table` finds `Hash Table` — you don't have to
know their exact vocabulary. Several topics widen the session rather than
narrowing it: `-t tree -t graph` means problems tagged with either.

A topic that matches nothing is refused outright, with the available
topics listed. An empty queue from a typo looks exactly like a finished
one, and there'd be no way to tell them apart.

Filtering applies to due reviews as well as new problems, so a topic
session stays on that topic.

### `algorhythm list` / `algorhythm stats`

```bash
algorhythm list      # every problem, its next due date and rep count
algorhythm stats     # counts of scheduled problems, reviews, attempts
```

### `algorhythm add` / `algorhythm seed`

```bash
algorhythm add two-sum                        # one problem, by LeetCode slug
algorhythm seed                               # bulk, from seeds/neetcode150.txt
algorhythm seed --list-path my-problems.txt   # bulk, from your own list
```

Both fetch the statement, import a reference solution, and generate test
cases. `seed` skips anything already present, so re-running it is safe
and only fetches what's new — that's how you extend the library later.

A slug list is one slug per line; `#` starts a comment.

---

## Where things live

```
~/.local/share/algorhythm/
├── algorhythm.db        schedule, reviews, attempts
├── problems/<n>-<slug>/ statement, examples, stubs, reference, tests
└── cache/cpp/           compiled C++ binaries, content-hashed
```

Problem content is files, not database rows, so it stays greppable and
hand-editable when a fetch comes out wrong. Set `ALGORHYTHM_HOME` to use
a different root — useful for trying things without touching your real
library:

```bash
ALGORHYTHM_HOME=/tmp/scratch algorhythm review
```

---

## How a rep is judged

Test cases come from two places. **Example cases** carry LeetCode's own
stated outputs. **Oracle cases** are generated by perturbing the example
input one parameter at a time and running a reference solution to get
the expected output; candidates the reference rejects are dropped, as are
candidates where the Python and C++ references disagree — that
disagreement is the only signal available that an input fell outside the
problem's stated constraints.

The reviewer is given your solution, the reference, and the concrete test
results. Grounding it that way turns "is this good?" into "how does this
differ from that?", which small models are much better at.

Some problems accept answers in any order. Those are marked `unordered`
and compared after sorting at every level, so a correct answer that
groups differently still passes. Problems where order *is* the answer —
a level-order traversal — are deliberately not marked.

---

## Curated overrides

Upstream data is imperfect: some reference solutions don't parse, some
test cases can't be written as JSON (a linked list with a cycle), and
"in any order" appears only in prose. `algorhythm/curated/<slug>/` holds
corrections that win over what seeding fetches:

| File | Overrides |
|---|---|
| `reference.py` / `reference.cpp` | The fetched reference solution |
| `tests.json` | The generated test cases, entirely |
| `problem.json` | Problem fields, e.g. `{"comparison": "unordered"}` |

Every part is optional. A problem with no directory seeds normally.

---

## What isn't supported

`seeds/neetcode150.txt` holds the full list; 129 of the 150 seed and
work. The rest are reported and skipped:

- **Design problems** (LRU Cache, Min Stack, Trie) define their own class
  and are driven by a sequence of operations, so there's no single entry
  point to test.
- **Premium problems** have no public statement.
- **Four shapes the codecs can't express** are commented out of the list,
  each with its reason — a list *of* linked lists, random pointers, tree
  nodes passed as bare values, and problems where any valid topological
  order is correct.

Nine problems have no C++ reference: upstream ships files holding several
`class Solution` definitions, and others that are simply wrong. A
reference that can't reproduce LeetCode's own stated outputs is discarded
rather than shown to you as the recommended solution. Those reps still
run in C++; they just have nothing to compare against.

---

## Development

```bash
pytest                    # the full suite
pytest -W error           # how CI-quality runs should look; output stays clean
```

The editor tests launch real nvim, and the C++ tests invoke the real
compiler; both skip themselves if the tool isn't installed. That
matters — the one bug that made `:w` silently do nothing was invisible to
every test that didn't drive a real editor.

Design notes and the build plan are in `docs/superpowers/`.
