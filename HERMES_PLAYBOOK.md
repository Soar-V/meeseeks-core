# HERMES_PLAYBOOK.md — Build & Verification Discipline

**Audience:** Hermes (builder agent).
**Purpose:** Reduce verification misses, catch failure classes early, keep build cycles cheap.
**When to consult:** Before declaring any build "done." When a fix is applied but the symptom persists. After hitting a new class of bug — add it to §6.
**Companion doc:** MEESEEKS_PLAYBOOK.md covers meeseeks design. This covers how Hermes builds them.

---

## 1. The "Done" checklist

A build is NOT done until every box is checked.

- [ ] Code compiles, unit and integration tests pass in isolation.
- [ ] Code is committed and pushed to the right branch.
- [ ] Running deployment process has been **restarted** to pick up the change.
- [ ] Verification happened **inside the running process** — not a separate REPL or shell.
- [ ] End-to-end smoke test ran in the actual deployment. User-visible behavior matches expectations.
- [ ] Token spend for the build is logged and within target (~$5 unless explicitly flagged).

If any box is unchecked, do not report the build as complete. Report what's done and what's pending instead.

If a build is heading above $5 of spend without resolution, STOP and report status to Alex BEFORE continuing. He'd rather make a scope decision than discover the overspend after the fact.

---

## 2. Verify in-process. Always.

The single most expensive class of failure we've hit: verifying a change in a separate Python session and assuming the running daemon matches. **Imports are cached. Daemons hold state. A REPL telling you "the import works" tells you nothing about whether the bot has loaded the change.**

Acceptable in-process verification:
- Startup log line, e.g. `Registered meeseeks: ['research_prospect', 'fixture']` printed when the bot boots.
- A live debug command (e.g., `/registry`, `/status`) that returns current state from the running process.
- A health check or status endpoint that reflects live config.

Not acceptable:
- `python -c "from meeseeks import registry; print(registry)"` in a fresh shell.
- Importing the package in a notebook.
- Reasoning from "the file on disk says X, so the bot is using X."

**Rule:** if verification is happening anywhere other than inside the daemon's process, it doesn't count.

---

## 3. Diagnostic order when something breaks at runtime

When a "fixed" bug still appears in the running deployment, work the list IN ORDER. Don't jump to step 4 before clearing 1, 2, and 3.

1. **Is the running process actually loading the change?**
   - `ps aux | grep <process>` — check process start time vs last commit.
   - If the process started before the commit, restart it and retest. Stop here unless retest still fails.

2. **Is the change in the right environment?**
   - `which python` and `pip show <pkg>` from inside the daemon's environment, not your shell.
   - Editable installs (`pip install -e`) only affect the venv they were run in. Multi-venv deployments need an explicit reinstall in the daemon's venv.

3. **Is the abstraction being bypassed?**
   - Hardcoded magic strings, fast-paths, Layer 1 rules picking specific names instead of deferring to the router.
   - Grep the codebase for the symptom value (e.g., `grep -r "url_research"`).

4. **Only now: dig into the code logic itself.**

Steps 1 and 2 cost minutes. Step 4 can cost hours. Order matters.

---

## 4. Test design

- Every conditional branch needs at least one test that exercises it.
- For layered architectures (Layer 1 hard rules → Layer 2 LLM router): every Layer 1 branch needs a test asserting it either (a) routes to a real registered name or (b) defers to the next layer.
- "Tests pass" is necessary, not sufficient. Green coverage that misses a branch is worse than no tests because it produces false confidence.
- Before closing a bug fix, write the test that would have caught the bug. If it can't be written, the fix is not understood well enough — diagnose more before patching.

---

## 5. Packaging discipline (meeseeks-core)

- Every subpackage intended for downstream import must be declared in `pyproject.toml` (`[tool.setuptools.packages.find]` or equivalent).
- Test packaging by installing from a fresh venv via the published artifact (wheel, `git+https`, or PyPI) — NOT via `pip install -e` from local src.
- "Editable install works in dev" ≠ "the package ships correctly." Verify both before any release.

---

## 6. Failure-mode catalog

Add a one-line entry when a new class of bug bites us. Keep terse. Curated, not exhaustive (per VISION §6).

- **2026-05 — Registry confirmed in REPL, bot still broken.** Verification in the wrong process; daemon was stale. Fix: restart, log registry on startup.
- **2026-05 — Build 17 integration tests missed Layer 1 URL routing branch.** Coverage gap in a conditional. Fix: enumerate all Layer 1 branches in test design before closing.
- **2026-05 — meeseeks-core v0.1.0 wheel shipped hollow.** `pyproject.toml` didn't include `meeseeks/` and `toolkits/` subpackages, so installs got the framework engine but no canonical meeseeks. Fix: declare subpackages in pyproject.toml + verify from fresh-venv install.
- **2026-05 — Hardcoded `url_research` in router Layer 1.** Fast-path bypassed the registry. Fix: defer URL-containing messages to LLM router instead of hardcoding meeseeks names. Layer 1 should set spawn priors, not pick specific meeseeks.
- **2026-05 — Deferred wiring placeholder survived to production (Build 20).** `_spawn_fn` called `cls.Input()` with a comment "real routing in Build N." Build N shipped the router but never closed the loop. No test exercised the path with a real meeseeks. Lesson: when a comment defers work to a future build, confirm that build closed it, or grep for the placeholder string. `inputs` is now a required arg (no default) so the compiler catches the next miss.

---

## How to use this doc

- **Read §1 before declaring any build done.** It takes 30 seconds.
- **Read §3 the moment a "fix" doesn't work in the deployment.** Almost always saves a wasted diagnosis loop.
- **Update §6 whenever a new failure class shows up.** Future builds get the lesson for free.
- **Keep this doc tight.** If it grows past ~150 lines, something is fluff. Trim.
