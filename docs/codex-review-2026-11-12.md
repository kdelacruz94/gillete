# Review of the Codex build, 2026-11-05 to 2026-11-12

Written by Claude after the Codex thread failed mid-turn during a T3 Code
update. It records the grades, the reasons for the change of priority
recorded in `progress.md`, and process lessons worth reusing in other
agent-run projects. The project state itself lives in `progress.md`.

## What Codex delivered

78 commits, about 16k lines of source and 13k lines of tests. 1,210 tests
pass (re-run independently). Dozens of hardware experiments ran on the
owner's own mice, including writes to onboard memory, a host freeze
mid-test and USB drops. Every one was journaled and restored, with
byte-for-byte readback. No configuration was lost.

## Grades

| Area | Grade | Basis |
|---|---|---|
| Plan (interview + `specification.md`) | A− | 15 questions with recommendations; captured the owner's real examples and the right guardrails (explicit Save to Mouse, no silent substitution, "original" means the Synapse setup, input-remapper kept until proven). Missing: any milestone before "everything verified on both mice". |
| Hardware safety | A | Journal, write, read back, restore, every time. Found and fixed real desktop issues (F23 as TouchpadOff, F20 triggering mic mute, a reconnect race). |
| Code and tests | B+ | Clean core (engine, profile model). Debts: about 25 of 101 modules are one-off experiment runners shipped in the product package; development-hardware results are hardcoded as prose in `diagnostics.py`. |
| Prioritization | C− | After 8 days the owner could not use the app: no real profile, no service, input-remapper still in charge. Late turns went to Synapse polling flags, storage compaction, wired onboard writes and editor polish. |
| Use of the owner's time | C | About 25 separate approval prompts, one narrow test each, many failing because the wireless mouse slept. The owner had to say "keep going, I don't want to have to keep asking you to proceed" and answered "Later — continue building" six times. |
| Docs and handoff | C | `progress.md` grew into a ~3,000-line append-only log with a stale "Still required" list; the README mixed user instructions with lab procedures. |
| Overall | B− | Excellent engineering aimed at the wrong next step. |

## What changed after the review

- **Daily use first.** Real profiles, both mice under the service, login
  startup, then input-remapper off. Onboard/Synapse parity comes after.
  The first live session ran the same evening (see `progress.md`).
- **One hardware session, one approval, a written checklist.** Keep the
  cable connected or the mouse awake to avoid sleep timeouts.
- **Ask the owner when they are the answer.** The eight unresolved V2
  Synapse functions were settled by one question (retired), not more
  research.

## Lessons for other agent-run projects

1. **Put a usable milestone before the finish line.** A spec whose only
   acceptance criterion is "everything verified" lets an agent stay in
   depth-first research indefinitely. Name the first point at which the
   owner can use the thing, and reach it early.
2. **Batch human-in-the-loop work.** Per-test approvals cost the owner more
   than the tests themselves. Plan a session, state its scope once, and
   have the agent drive while the human only does the physical steps.
3. **Measure results, don't ask for impressions.** A tiny focused logging
   window (`tools/keycheck_window.py`) turned every "did it work?" into a
   timestamped log the agent checks itself, including repeat rates and
   cancellation timing.
4. **Keep state docs short and current.** An append-only log is not a
   status page. Keep a short current-state section plus a separate history.
5. **Don't lock typos into tests.** Old tests asserted the run-together
   "All42" text, so fixing the string needed a test change too.
6. **Check machine-wide blockers before physical tests.** This machine runs
   `agent-awake.service`, a logind *block* inhibitor on sleep, so a suspend
   test cannot start until it is stopped.

## T3 Code lesson: a "failed" Codex run can keep working

When T3 Code restarted during the update, it marked the Codex turn cancelled
and the following resume attempts failed. The Codex process carried on
without being shown in T3 and made two more commits (`33470fb`, `d9b8372`)
after T3 had stopped tracking it. Before resuming or handing over a thread
whose run failed during a restart, check `git log`, the working tree and
running `codex` processes rather than trusting the thread status. Codex's
`/goal` stays set after such a failure, so resuming that thread restarts the
same loop; never run it alongside another agent in the same checkout.
