# GreenX — Energy-Aware OS Extension for xv6-riscv

A plain-English walkthrough of every feature, how it works under the hood,
and why it matters.

---

## What is GreenX?

Modern operating systems have no idea how much energy a process is consuming.
They schedule processes fairly (or by priority), but they never ask: *"is this
process worth the electricity it's burning?"*

GreenX adds a thin energy-awareness layer to xv6 — a teaching OS that runs on
RISC-V — so that the kernel can:

- Label processes as low, normal, or high priority for energy purposes
- Count how many CPU timer ticks each process consumes
- Kill a process that goes over a set energy limit
- Expose all of this to user programs through three new system calls

There are no hardware power sensors involved. GreenX treats **CPU timer ticks
as a proxy for energy** — the more ticks a process uses, the more energy it
is assumed to consume. It is a software model, but it is grounded in a real
principle: CPU time is the dominant factor in a process's energy footprint.

---

## Feature 1 — Urgency Levels

### What it does

Every process gets a label: **LOW**, **NORMAL**, or **HIGH** urgency.

| Label  | Value | Meaning |
|--------|-------|---------|
| LOW    | 0     | Background work — skip it most of the time |
| NORMAL | 1     | Default — runs as usual |
| HIGH   | 2     | Reserved for future priority boosting |

### How it works

A new field called `urgency` was added to the kernel's process struct
(`struct proc` in `kernel/proc.h`). Every new process starts with
`urgency = URGENCY_NORMAL` (1). When a process forks a child, the child
**inherits** the parent's urgency automatically — so if a low-priority
background job spawns children, those children are also treated as low priority
without any extra work.

```
Parent (urgency=LOW) → forks → Child (urgency=LOW)  ✓ inherited
Parent (urgency=NORMAL) → forks → Child (urgency=NORMAL)  ✓ inherited
```

### Where the code lives

- `kernel/proc.h` — defines the `urgency` field and the three constants
- `kernel/proc.c` `allocproc()` — sets `urgency = URGENCY_NORMAL` on birth
- `kernel/proc.c` `kfork()` — copies `urgency` from parent to child

---

## Feature 2 — Energy-Aware Scheduler

### What it does

The scheduler is the part of the kernel that decides which process runs next
on each CPU core. Normally it just round-robins through all RUNNABLE processes
fairly. GreenX changes this: **LOW urgency processes get skipped twice before
they are allowed to run once.**

Think of it like a queue at a coffee shop where regular customers (NORMAL) go
straight to the counter, but customers holding a "low priority" token have to
let two other customers go first before they get served.

### How it works

A counter called `skip_count` is stored in each process. Every time the
scheduler considers a LOW urgency process and decides to skip it, `skip_count`
goes up by one. Once `skip_count` reaches 2, the process is allowed to run and
`skip_count` resets to 0. NORMAL and HIGH processes are never skipped.

```
Round 1: LOW process seen → skip_count = 1, skip
Round 2: LOW process seen → skip_count = 2, skip
Round 3: LOW process seen → skip_count resets to 0, RUN
```

In terms of CPU share, a LOW process gets roughly **1 out of every 3 chances**
compared to a NORMAL process. This saves energy for lower-importance work
without starving it entirely.

Additionally, when there are absolutely no RUNNABLE processes to schedule, the
scheduler now calls `intr_on()` followed by the RISC-V `wfi` instruction
(**W**ait **F**or **I**nterrupt). This halts the CPU core until the next
hardware interrupt arrives, instead of spinning in a hot loop doing nothing —
a genuine energy saving when the system is idle.

### Where the code lives

- `kernel/proc.c` `scheduler()` — the skip logic sits inside the main
  scheduling loop, just before the `swtch()` call that hands the CPU to a
  process

---

## Feature 3 — Tick Counting (Energy Metering)

### What it does

Every time the hardware timer fires (roughly 10 times per second in xv6),
GreenX increments a counter called `ticks_used` for whichever process is
currently running. This gives a running total of how much CPU time — and by
proxy, how much energy — each process has consumed since it was created.

### How it works

xv6 already has a timer interrupt that fires periodically. In the interrupt
handler (`usertrap` in `kernel/trap.c`), GreenX hooks in right before the
kernel calls `yield()` (which gives the CPU to the next process):

```
Timer fires
  → GreenX: p->ticks_used++
  → GreenX: check budget (see Feature 4)
  → kernel: yield() — switch to next process
```

`ticks_used` starts at 0 when a process is created and only goes up. It is
never reset during the life of the process. This makes it easy to ask
"how much has this process consumed in total?" at any point.

### Where the code lives

- `kernel/proc.h` — the `ticks_used` field on `struct proc`
- `kernel/proc.c` `allocproc()` — initialised to 0
- `kernel/trap.c` `usertrap()` — incremented on every timer interrupt

---

## Feature 4 — Energy Budget Enforcement

### What it does

A process can be given an **energy budget** — a maximum number of ticks it is
allowed to consume. If it goes over the limit, the kernel **kills it**,
printing a message to the console explaining why.

This is like giving a process a prepaid electricity card. When the credit runs
out, the process is shut down. Useful for preventing runaway processes,
background jobs, or student code from hogging CPU forever.

### How it works

A field called `energy_budget` is stored in each process. A value of `0` means
"unlimited" (the default). When a process sets a budget (via `setbudget`), that
number is stored. On every timer tick, after incrementing `ticks_used`, GreenX
checks:

```
if energy_budget > 0 AND ticks_used > energy_budget:
    print "GreenX: process X exceeded energy budget. Killed."
    set p->killed = 1
```

Setting `killed = 1` does not immediately stop the process. xv6 checks this
flag at safe points (like when returning from a system call or interrupt) and
then calls `exit(-1)` on the process's behalf. This ensures the process dies
cleanly — locks are released, files are closed, the parent is notified.

### Example

A process calls `setbudget(10)`. After 11 timer ticks, the kernel prints:

```
GreenX: process 5 (energytest) exceeded energy budget. Killed.
```

And the process terminates. The parent's `wait()` call returns normally,
just as it would if the child had called `exit()` itself.

### Where the code lives

- `kernel/proc.h` — the `energy_budget` field on `struct proc`
- `kernel/proc.c` `allocproc()` — initialised to 0 (unlimited)
- `kernel/trap.c` `usertrap()` — the budget check runs on every timer tick

---

## Feature 5 — Three New System Calls

System calls are the bridge between user programs and the kernel. GreenX adds
three new ones. From a user program's perspective they are just C functions,
but underneath each one crosses into the kernel to read or write protected
process state.

---

### `seturgency(int level)` — syscall 22

**What it does:** Sets the urgency of the calling process.

**Arguments:** `level` — must be 0 (LOW), 1 (NORMAL), or 2 (HIGH).

**Returns:** `0` on success, `-1` if the level is out of range.

**Example:**
```c
seturgency(0);  // "I am a background job, deprioritise me"
seturgency(2);  // "I am time-sensitive"
seturgency(99); // returns -1, invalid
```

**How it works in the kernel:**
The kernel reads the integer argument from the process's register `a0`, checks
it is between 0 and 2, then writes it directly to `myproc()->urgency`. Simple
and fast — no locking needed because a process only ever sets its own urgency.

---

### `getpenergy(int pid)` — syscall 23

**What it does:** Reads the `ticks_used` counter for any process by its PID.

**Arguments:** `pid` — the process ID to query.

**Returns:** The number of ticks that process has used, or `-1` if no process
with that PID exists.

**Example:**
```c
int before = getpenergy(getpid());
// ... do some work ...
int after = getpenergy(getpid());
printf("I consumed %d ticks\n", after - before);

getpenergy(9999); // returns -1, no such process
```

**How it works in the kernel:**
The kernel walks the entire `proc[]` table (the fixed array of all process
slots). For each slot, it acquires the spinlock, checks if `p->pid` matches,
reads `ticks_used`, releases the lock, and returns. The lock is essential —
without it, a timer interrupt on another CPU core could be incrementing
`ticks_used` at the same moment, giving a corrupted read.

---

### `setbudget(int budget)` — syscall 24

**What it does:** Sets the energy budget (tick limit) for the calling process.

**Arguments:** `budget` — maximum ticks allowed. `0` means unlimited.

**Returns:** `0` on success, `-1` if budget is negative.

**Example:**
```c
setbudget(50);  // allow up to 50 timer ticks, then die
setbudget(0);   // remove the budget limit
```

**How it works in the kernel:**
The kernel reads the integer argument, checks it is not negative, and writes
`(uint64)budget` to `myproc()->energy_budget`. From this point on, every timer
tick checks this value and kills the process if it is exceeded.

---

### How system calls flow end-to-end

```
User program calls seturgency(0)
  → usys.S stub: loads syscall number 22 into register a7, executes ecall
  → CPU traps into kernel, lands in usertrap()
  → usertrap() calls syscall()
  → syscall() looks up syscalls[22] → sys_seturgency
  → sys_seturgency() runs, sets myproc()->urgency = 0
  → returns 0 to user via register a0
  → CPU returns to user space
```

The mapping of number → function lives in `kernel/syscall.c`. The numbers
themselves are defined in `kernel/syscall.h`. The assembly stubs that user
programs call are generated from `user/usys.pl`.

---

## Feature 6 — User-Space Tools

### `greenstat` — Energy Dashboard

Running `greenstat` in the xv6 shell prints a table of every live process and
how many ticks it has used:

```
GreenX Energy Report
--------------------
PID     TICKS
1       0
2       0
3       3
--------------------
Processes: 3  |  Total ticks: 3
```

It works by calling `getpenergy(pid)` in a loop from PID 1 to 64. Any PID
that returns `-1` (no such process) is silently skipped. This gives a
real-time snapshot of energy consumption across the whole system.

---

### `energytest` — Test Suite

`energytest` is a self-contained program that verifies all six GreenX
behaviours automatically and prints PASS or FAIL for each:

| Test | What it checks |
|------|---------------|
| 1 | `seturgency` accepts 0/1/2 and rejects 99 |
| 2 | `getpenergy` grows after a busy loop; returns -1 for unknown PID |
| 3 | A forked child can `sleep()` and exit cleanly |
| 4 | A child with `setbudget(3)` that spins forever gets killed by the kernel |
| 5 | A LOW urgency child can still call `getpenergy` on itself |
| 6 | A child that `exec`s `greenstat` exits with status 0 |

---

## How All the Pieces Connect

```
┌─────────────────────────────────────────────────────┐
│                   User Space                        │
│                                                     │
│  energytest / greenstat                             │
│       │                                             │
│  seturgency()  getpenergy()  setbudget()            │
│  (user/user.h + user/usys.pl stubs)                 │
└──────────────────────┬──────────────────────────────┘
                       │  ecall (trap into kernel)
┌──────────────────────▼──────────────────────────────┐
│                  Kernel Space                       │
│                                                     │
│  kernel/syscall.c  →  kernel/sysproc.c              │
│  (dispatch table)      (sys_seturgency etc.)        │
│                                                     │
│  kernel/proc.h  ←─  struct proc fields:             │
│                       urgency, skip_count,          │
│                       ticks_used, energy_budget     │
│                                                     │
│  kernel/proc.c                                      │
│   allocproc()  — initialise fields to defaults      │
│   kfork()      — inherit urgency from parent        │
│   scheduler()  — skip LOW processes 2/3 times       │
│                  wfi when nothing to run            │
│                                                     │
│  kernel/trap.c                                      │
│   usertrap()   — on timer: tick++, check budget     │
└─────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

**Why timer ticks as an energy unit?**
Real energy measurement requires hardware power sensors that xv6 does not have.
Timer ticks are a universally available, per-process proxy for CPU time, which
correlates strongly with energy consumption on a single-core workload.

**Why skip LOW processes 2 out of 3 times, not more?**
Skipping too aggressively risks starvation — a process that never runs cannot
make progress even on legitimate background work. A 2-skip rule gives LOW
processes roughly 33% of a NORMAL process's share, which is a meaningful
reduction without permanent starvation.

**Why does `energy_budget = 0` mean unlimited?**
Zero is the natural zero-value for an integer field. Making `0` mean "no
limit" means that newly created processes are safe by default — they will
never be accidentally killed just because the budget was never set.

**Why does the budget kill use `p->killed = 1` instead of `exit()`?**
The timer interrupt runs in kernel mode, potentially with spinlocks held. It is
not safe to call `exit()` directly from there. Setting `killed = 1` defers the
actual teardown to a safe checkpoint — the next time the process returns from a
system call or interrupt — where the kernel can clean up properly.

**Why does `getpenergy` need a lock?**
`ticks_used` can be incremented by a timer interrupt on any CPU core at any
time. Without the spinlock, a read of `ticks_used` from `getpenergy` on one
core could race with an increment from a timer interrupt on another core,
producing a partially-written, corrupted value. The lock prevents this.

---

## Statement of Contribution

All three team members contributed equally to the design, implementation, testing, and documentation of the GreenX project.

| Member | Contribution |
|--------|-------------|
| Ashan  | Equal contribution |
| Nolan  | Equal contribution |
| Sujay  | Equal contribution |

We, the undersigned, confirm that the above statement accurately reflects the contributions of each team member.

**Ashan** ___________________________

**Nolan** ___________________________

**Sujay** ___________________________
