# Aether desk log

Not a README. This is the thread between Grok and ChatGPT.
Read the whole file before touching code. Append a new entry when you start. Append again when you end. Do not edit someone else’s entry.

## How this desk works

- **Place / ship:** one agent implements.
- **Read / comment:** the other agent reviews that SHA only. No drive-by rewrites in the same files.
- Capability, not idle time:
  - **Grok** owns strategy, paper fills, journal, engine hooks, live-block, Azure API behavior.
  - **ChatGPT** reviews and stress-tests that stack first; UI only after the open strategy slice has `AGREE DONE` from both, or Terry explicitly asks for UI.
  - Cross the lane only if the owner writes `HANDOFF` and the lock is `open`.
- **Lock:** list exact paths. If a path is locked, the other agent may only comment here.
- **Stamps:** `START YYYY-MM-DD HH:MM TZ` and `END YYYY-MM-DD HH:MM TZ` plus the commit SHA you left.
- If two starts overlap on the same path, the second start is invalid. Stop. Comment. Wait for their END.

## Strategy stack first

- Until both `AGREE DONE` on the current strategy slice, **do not** spend a turn on dock, theme, ticker, charts, or copy.
- Order of work: rule → clock → fills → journal → engine wiring → then UI.
- ChatGPT’s first output on an open strategy slice is a written review in this thread. Code in those files only after Grok ENDs a place and the lock is open, or Terry says to place.
- A pretty desk on a leaking rule is out of order.

## Done means both say done

- A slice is not finished when one agent stops. It is finished when **both** write `AGREE DONE` on the same slice name, with SHA and time.
- Until the second `AGREE DONE`, keep working or keep reviewing. Do not wander into a new slice that steps on the open one.
- After both agree, write **`docs/REPORT-<slice>.md` together**: Grok drafts the strategy/runtime half, ChatGPT drafts the test/review half. The report must say *why* it is complete (what shipped, what was tested, what is still blocked, what must not be called live).
- No solo “we are done.” If the other agent has not agreed, the slice is open.

## Persist and push each other

- Every START that changes code must **push** before END. Unpushed work does not exist on this desk.
- Every END must name the SHA and the next concrete ask for the *other* agent. Do not END with silence.
- If the other agent goes quiet, the next START begins with: what they last shipped, what is still weak, and a direct push.
- Idle is not a state. Spare time is strategy RESEARCH or a waiting review.
- Push means a clearer rule and fewer bad entries. It does not mean arm live or break a lock.

## Spare-time research

- Research the strategy stack first (breakouts, ATR, cost hurdle, journal alignment).
- UI research waits until the open strategy slice is agreed done.
- Notes only. No code until Terry or the lane owner turns a note into a place.
- Do not research a way to arm live money in this file.

## Board

- Open slice: **strategy-stack** (review + frozen_hard_stop wiring + champion lookback 20). Not agreed done.
- Live execution: **blocked**
- Paper rule: 20-bar 5m Donchian, ATR compress/expand, cost hurdle, 5m entry clock, two-loss sit, one-way trail helper (helper not fully wired in engine)

## Locks

- open

---

## Thread

### Grok — START 2026-09-21 03:08 EDT

Terry: strategy logic/stack first. UI waits. ChatGPT reviews the four strategy files this turn.

### Grok — END 2026-09-21 03:08 EDT

SHA: this commit.
**Push to ChatGPT:** START. Review only. No dock.
