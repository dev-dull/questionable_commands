# Local AI on a 2016 Dual-Xeon Server — the research behind the build

This is the working document behind the Local AI episode: the hardware analysis, the model
choices, what broke, and what the numbers actually turned out to be. `HOST_SETUP.md` is the
runbook if you just want to build one. This file is the *why*.

**Read it as two things at once:** a record of what happened on this specific machine, and a
guide to the decisions you'd face building something similar. Where those diverge — where a
choice only makes sense because of *this* box's quirks — it says so.

The short version: a 2016 dual-socket Xeon board and a 2018 gaming GPU will run a modern
mixture-of-experts model at usable speed, but almost every performance question comes down to
memory bandwidth rather than the things people usually shop for.

## What the box is for

| # | Workload | Shape | Verdict on this hardware |
|---|---|---|---|
| 1 | **Claude Code against a local model** | Interactive, agentic, huge system prompt + tool definitions, many tool calls per turn | ⚠️ Works, but it's the hardest ask. See the honest expectations below |
| 2 | **Résumé ↔ job-description fitness scoring, A/B tested** | Batch, structured JSON out, latency-irrelevant, many repeats | ★ **Best fit.** What this hardware is genuinely good at |
| 3 | **Aider for development work** | Interactive but single-shot-ish; already Anthropic-compatible | ✅ Easiest. Drops in with two environment variables |

Everything below is organised around making those three work, in that order of difficulty. If
you're building for different workloads, the shapes still transfer: interactive agentic work is
the demanding case, batch work is where cheap hardware shines.

---

## Hardware
| Part | Spec | What it means for LLMs |
|---|---|---|
| Motherboard | Asus Z10PE-D16 WS | 6× PCIe 3.0 x16 (all six only with both CPUs populated); dual-socket = **2 NUMA nodes** |
| CPU | 2× Xeon E5-2630 v4 — **engineering samples** | 20c/40t total, 85 W each. Broadwell-EP: **AVX2 only — no AVX-512, no AMX**. Reports as `Genuine Intel(R) CPU 0000 @ 2.10GHz` — note **2.10 GHz vs retail's 2.20**, so the ES bin is down-clocked at base too |
| Memory | **8× 8 GB** DDR4-2133 ECC RDIMM (Samsung M393A1G40DB0-CPB2Q, 1Rx4) | **64 GB, 32 GB per socket, 1 DIMM per channel.** Reduced from 16 after unresolvable POST faults — see the troubleshooting log. Silver lining: 1 DPC means **full 2133 and balanced interleaving, ~68 GB/s/socket** |
| Expansion | 4× PCIe 3.0 x16 (x16 mode) + 2× PCIe 3.0 x16 (x8 mode) | Your "four x16" memory is right — those are the four full-width ones. Top slot is physically blocked by RAM for long cards |
| GPU | Zotac RTX 2080 8 GB | Turing, **sm_75**, 448 GB/s, FP16 tensor cores. No BF16, no native FP8/FP4/MXFP4 |
| GPU spares **on hand** | **6× GTX 1660 Super 6 GB** | TU116, **also sm_75**, 336 GB/s, **no tensor cores**. Free VRAM you already own — see Upgrade B, this may be the biggest available win |
| Boot disk | 120 GB SSD | Fine. OS + logs only |
| Model store | 8 TB HDD, **flagged for SMART errors** | Correct risk call — see the triage protocol below. Models are re-downloadable |
| Disks fitted | **Two, by design** | The boot SSD and the 8 TB. Anything not re-downloadable — eval sets, results — lives **off-box**, not on a third drive here |
| PSU | Corsair 1200 W | Not a constraint. Idle draw is the thing to watch |

### The one number that matters
Token *generation* on CPU is memory-bandwidth-bound, not compute-bound. Core count is nearly
irrelevant; **per-socket memory bandwidth** is the ceiling. Every performance estimate below is
derived from `bytes_of_active_weights_read_per_token ÷ available_bandwidth`.

That number should be **~68 GB/s per socket** — DDR4-2133, quad channel — because the 8-DIMM
config is 1 DIMM per channel with balanced interleaving. **Verify rather than assume:**
`dmidecode -t memory | grep -i configured` should read **2133**.

> **No 2 DPC comparison exists for this machine.** The 128 GB build never POSTed, so the 1866
> figure is only ASUS's footnote and other owners' reports — never measured here. The 2 DPC
> downclock remains a good *forward-looking* reason to prefer 8× 16 GB over 16× 8 GB when
> upgrading, but it is not something this box has demonstrated.

The corollary that drives the whole build: **a model that fits inside one socket's 64 GB runs
faster than a model that has to straddle both sockets.** Crossing the QPI link to reach the other
CPU's RAM costs more than the extra bandwidth buys back. This is counterintuitive and it is the
single best on-camera demo this machine has to offer.

### The "v0000" CPUs — you have engineering samples

`Genuine Intel(R) CPU 0000 @ 2.20GHz` instead of `Intel(R) Xeon(R) CPU E5-2630 v4` is the
canonical signature of an **Engineering Sample (ES) or Qualification Sample (QS)** chip. Intel
documents this identification method themselves. ES E5-2630 v4 parts (`QHVK` stepping) are all
over the used market — if you bought these cheap, this is almost certainly what happened.

Confirm it:
```bash
lscpu | grep -E 'Model name|Stepping'
dmidecode -t processor | grep -E 'Version|ID|Signature'
grep microcode /proc/cpuinfo | sort -u     # ES chips often report 0x0 or an odd revision
```

**For this workload: not a roadblock.** ES chips have the same cores, the same AVX2 units, and the
same memory controller as retail. Nothing in llama.cpp cares. Your box works.

**Three things it does affect, in ascending order of importance:**

1. **Turbo bins are often lower on ES silicon** than the retail part's rated boost. On a
   bandwidth-bound workload this is nearly irrelevant — you're waiting on DRAM, not clocks.
2. **Microcode updates may not apply.** ES steppings aren't covered by retail microcode packages,
   so you're stuck at whatever the BIOS carries. Practically: no Spectre/Meltdown mitigations. For
   a LAN-only inference box running your own models, that's an acceptable risk — but don't put
   anything multi-tenant or internet-facing on it.
3. **⚠️ Do not flash the BIOS.** This is the real hazard. ES/QS steppings are supported only by
   BIOS revisions that happen to carry their microcode, and vendors *remove* pre-production
   microcode from later releases. A routine BIOS update is a plausible way to turn this machine
   into a paperweight that won't POST. If the board works today, leave the firmware alone. If you
   must update, record the current version and confirm you can flash back first.

The one place this genuinely constrains you is the upgrade path — see the CPU/memory section below.
Don't mix an ES chip with a retail chip across the two sockets; matched steppings are the rule.

---

## Memory — RESOLVED: settled at 64 GB

Running **8× 8 GB = 64 GB at 1 DIMM per channel**. 128 GB was attempted and abandoned — individual
module/slot faults, not a compatibility problem. Consequence: gpt-oss-120b (61 GB) is blocked until
upgrade A1; everything else in the plan works.

**Rules that came out of it, worth keeping:**

- **Each populated CPU needs at least one DIMM.** Minimum dual-CPU config is `A1` + `E1`.
- **Valid balanced configs are 8 or 16 — nothing between.** 12 splits the interleave sets and makes
  bandwidth inconsistent.
- **Read the `ERR_DIMMA1`–`ERR_DIMMH1` LEDs** next to the slots before swapping anything.
- **Bisect from a known-good config.** Reseating everything produces no information; using a
  working set as a test jig produces one clean verdict per boot.
- **`CLRTC` is the CMOS jumper**, and pulling the battery does nothing while AC is connected —
  +5VSB keeps the RTC alive.
- **A whole bank failing together means socket pins, not four dead sticks.** Photograph the LGA2011-3
  socket with raking light before suspecting modules.

### The RAM itself is fine — ASUS QVL row 1

Your **Samsung M393A1G40DB0-CPB** is **the first row of ASUS's official QVL** for this board
(`Z10PE-D16_WS_TS700-E8_TS700-E8_V2_DIMM_AVL_20180328.pdf`, 2018/03/28 release):

| Vendor | Vendor P/N | Size | Module Spec | Rank | Memory Chip | RCD |
|---|---|---|---|---|---|---|
| Samsung | **M393A1G40DB0-CPB** | 8GB | DDR4-2133 ECC/REG CL15 | 1 | Samsung K4A4G045WD-BCPB | IDT 4RCD0124KC0ATG |

Your part number carries a `2Q` suffix (`M393A1G40DB0-CPB**2Q**`). That's a Samsung
packaging/revision code — `0Q`, `2Q`, and `3Q` variants all exist of the same module. Same DRAM,
same organisation, same speed bin. It's the module ASUS validated.

Everything else checks out too: RDIMM ✅ (board takes RDIMM and LR-DIMM), ECC Registered ✅,
1Rx4 ✅ (QVL rank column says 1), 128 GB total ✅ (max is 1024 GB), DDR4-2133 ✅ (matches the
E5-2630 v4's own 2133 ceiling).

**One thing worth checking if you're chasing a fault:** the QVL pins the *RCD* (registering clock
driver) as `IDT 4RCD0124KC0ATG`. Modules sold under one part number can ship with different RCDs
across production runs, and RCD mismatch is a real — if uncommon — source of "identical sticks,
different behaviour." If some of your sixteen came from different lots, that's a thing to rule out.

### Why 2 DIMMs per channel is worth avoiding (documented, not measured here)

ASUS's own spec footnote for this board, verbatim:

> **When installing E5-2600 v4/E5-1600 v4 CPUs:**
> — RDIMM: **2400MT/s is supported at 1 DPC only**
> — LR-DIMM: 2400MT/s is supported

And multiple owners of this exact board report that **filling all 16 RDIMM slots drops the bus to
1866 MT/s.** One report is precisely diagnostic: two quad-kits of DDR4-2133 ran at 2133 *separately*
and 1866 *together*.

On a workload whose ceiling is memory bandwidth, that is not a footnote:

| Config | MT/s | Per-socket bandwidth |
|---|---|---|
| **Current: 8 DIMMs, 1 DPC** | 2133 (verify) | **~68.3 GB/s** |
| 16 DIMMs, 2 DPC — *never POSTed here* | 1866 (reported) | ~59.7 GB/s |
| 8 DIMMs, 1 DPC, 2400-capable CPUs | 2400 | ~76.8 GB/s (**+12%**) |

**This machine has no 2 DPC datapoint** — the 16-DIMM build never ran, so the 1866 row is other
people's reporting, not a measurement from this box. It's a sound reason to buy 8× 16 GB rather
than 16× 8 GB when upgrading; it is not a result you can cite.

**The tok/s estimates elsewhere in this plan assume ~68 GB/s**, which the current 1 DPC config
should deliver. Confirm with `dmidecode` before trusting them.

### Measure it — five seconds, and it may be worth $100

```bash
sudo dmidecode -t memory | grep -E 'Size|Speed|Configured|Rank|Part Number|Locator' | less
```

`Speed:` is what the module is *rated* for. **`Configured Memory Speed:` is what it's actually
running at.**

**✅ Measured 2026-08-02: `2133 MT/s` across all 8 DIMMs.** The 1 DPC config is running at full
speed as predicted, so the ~68 GB/s per-socket figure the tok/s estimates use is the right
theoretical basis.

> **⚠️ Don't use `mbw` to check that.** The hardware baseline runs `mbw -q -n 10 1024` and reports
> ~3.5–4 GiB/s, which looks alarming next to 68 GB/s. It isn't a contradiction — **`mbw` is
> single-threaded**, and one Broadwell core cannot saturate four memory channels. It's a useful
> regression check and a useless absolute. For the aggregate number llama.cpp actually gets with
> 20 threads, use **Intel MLC** (`mlc --max_bandwidth`) or STREAM built with OpenMP.

The honest caveat: sources disagree on whether 2 DPC lands at 1866 or 2133. Intel's own RDIMM
validation table for E5-2600 v4 says 2133 at 2 DPC; ASUS's footnote only establishes that 2400 is
1-DPC-only; owner reports say 1866. It plausibly depends on rank loading — your 1Rx4 modules put
just 2 ranks on each channel, which is light, so 2133 may well hold. **Your board's answer is the
only one that counts, and `dmidecode` has it.**

### Decoding the B-range properly — the Grantley MRC table

ASUS's manual lumps `B0`–`BC` together as a useless "Memory Init." Intel's Technical Product
Specifications for **Grantley-platform boards (Xeon E5-2600 v3/v4 — same silicon as yours)**
publish the actual per-code MRC table. This is the real decoder ring:

| Code | Meaning |
|---|---|
| **`B0`** | **Detect DIMM population** |
| `B1` | Set DDR4 frequency |
| `B2` | Gather remaining SPD data |
| `B3` | Program registers at the memory-controller level |
| `B4` | Evaluate RAS modes and save rank information |
| `B5` | Program registers at the channel level |
| `B6` | Perform the JEDEC-defined initialization sequence |
| **`B7`** | **Train DDR4 ranks** — read DQ/DQS, receive-enable, write-levelling, write DQ/DQS |
| `B8` | Initialize CLTT/OLTT |
| `B9` | Hardware memory test and init |
| `BA` | Execute software memory init |
| `BB` | Program memory map and interleaving |
| `BC` | Program RAS configuration |
| `BF` | **MRC is done** |
| `E8` | *Fatal:* no usable memory (`01h` no SPD detected, `02h` all channels non-functional) |

---

## Storage: the 8 TB with SMART errors

Using a suspect disk for a re-downloadable model library is exactly the right risk trade — the
worst case is a re-download, not data loss. Two conditions make it safe:

**1. Triage it before you trust it.** "SMART errors" covers everything from one benign
reallocation to a drive actively shedding sectors. Look at the five attributes that actually
predict failure:

```bash
smartctl -a /dev/sdX | grep -E '^  (5|187|188|197|198) '
smartctl -t long /dev/sdX      # ~12h on an 8TB; check back with -a
```

- `5 Reallocated_Sector_Ct` — a stable non-zero count is survivable
- `187 Reported_Uncorrectable` / `198 Offline_Uncorrectable` — non-zero and rising is serious
- `197 Current_Pending_Sector` — **the one that matters most.** Sectors the drive can't read and
  hasn't remapped yet. A rising count means it's actively dying
- `188 Command_Timeout` — rising counts often mean cable/controller, not platter

Record the raw values today, re-check monthly. **The trend matters far more than the absolute
number.** A drive sitting at "5 reallocated, 0 pending" for six months is a working drive.

### ⚠️ Measured 2026-08-02 — worse than "SMART errors" implied

`ST8000VX0022-2EJ112` / `REDACTED`:

| Attribute | Raw value | Read |
|---|---|---|
| `5 Reallocated_Sector_Ct` | **31,360** | Enormous. This drive has remapped a *lot* |
| `187 Reported_Uncorrect` | **261** | Real uncorrectable read errors have happened |
| `197 Current_Pending_Sector` | **0** | ✅ Nothing waiting to be remapped right now |
| `198 Offline_Uncorrectable` | **0** | ✅ Nothing unreadable on the last scan |
| `188 Command_Timeout` | 8590065668 | Packed multi-counter field; don't read as one number |

**Honest assessment:** 31,360 reallocations is far past "a stable non-zero count is survivable" —
that phrasing was written before the numbers came in and it undersold this drive. It has been
through something. But **pending and offline-uncorrectable are both zero**, which is the pair that
says "damaged and stabilised" rather than "actively dying." The remapping already happened; the
drive is currently reading everything it's asked for.

**This doesn't change the decision, and arguably vindicates it.** Models are re-downloadable, ZFS
`copies=2` can self-heal isolated bad sectors, and nothing unique lives here. What it does change
is the monitoring bar: **if `197 Current_Pending_Sector` moves off zero, stop using the drive.** On
a disk with this history that's the transition from "scarred" to "failing," and there won't be much
warning. Check monthly against the artifact trend in `ansible/artifacts/clode/`.

**2. Use a filesystem that can detect *and repair* silent corruption.** This is where the choice
is not arbitrary — on a single disk, btrfs can detect bad blocks via checksum but has nothing to
repair from. **ZFS with `copies=2` actually stores a second copy of every block**, so a scrub can
heal a localized bad sector:

```bash
zpool create -o ashift=12 tank /dev/disk/by-id/ata-XXXX
zfs create -o copies=2 -o compression=off -o recordsize=1M tank/models
zpool scrub tank        # schedule monthly; zpool status shows repaired blocks
```

8 TB at `copies=2` gives ~4 TB usable — still 30× more than the model library needs.
`compression=off` because GGUF is already compressed; `recordsize=1M` suits large sequential
reads. Set up `zed` email/ntfy notifications so a scrub failure reaches you.

**What does *not* go on this disk:** the OS (that's the 120 GB SSD), your eval datasets, and your
A/B results. Those aren't re-downloadable.

> **This host deliberately has only two disks.** There is nothing here that's both durable and
> not the drive with 31,360 reallocated sectors — and that's fine, because **anything you can't
> re-download should leave the machine.** Eval sets, scoring results, and benchmark CSVs belong on
> whatever you already back up: a NAS, a workstation, a git repo.
>
> The Ansible storage role reflects this. With no `aihost_evaldata_disk_by_id` set it skips
> provisioning `/srv/evaldata` and says so, rather than silently landing research output on the
> failing disk. If you *do* fit a third drive, set that variable and the role picks it up.

Mount at `/srv/models`, point `HF_HOME` and `LLAMA_CACHE` at it.

---

## Software stack

**Settled: `llama-server` behind `llama-swap`.**

Two facts decide the whole architecture:

- **`llama-server` natively serves Anthropic's Messages API at `/v1/messages`** — streaming, tool
  use, vision. Claude Code points straight at it with an environment variable. No translation
  proxy, no LiteLLM, no `claude-code-router`. That collapses use cases 1 and 3 onto one server.
- **Every runner worth considering — llama-server, Ollama, LM Studio — calls the same ggml
  kernels.** Token generation on identical hardware lands within ~5–10%. The differences are
  ergonomics, not speed. Anyone promising a 3× speedup by switching runners is selling something.

So the only thing that matters in a manager layer is whether it restricts the flags you need. Pick
one that doesn't.

### The stack

| Layer | Choice | Why |
|---|---|---|
| Engine | **llama.cpp, built from source, CUDA on** | Only path to `--n-cpu-moe`, `-ot` regex, `--numa`, `llama-bench`, and `/v1/messages` |
| Front door | **llama-swap** | One endpoint, both API dialects (OpenAI **and** Anthropic), swaps models on demand from a YAML map. This is the keystone — see below |
| Chat UI | **Open WebUI** in Docker | For non-CLI use and RAG. Also a callback to Ep. 0x004 |
| Orchestration | systemd units | Two services. Resist the urge to reach for Kubernetes |

**Why llama-swap is the keystone here.** You have three workloads, two users, and 8 GB of VRAM —
you cannot keep three models resident. llama-swap reads the `model` field on each incoming request,
starts the right `llama-server` with the right flags if it isn't already running, and routes to it.
One YAML file, one port, both dialects. A Claude Code session asks for `coder`, the eval harness
asks for `scorer`, and the box does the right thing without either of you touching a terminal.

**The working config lives in `HOST_SETUP.md` Phase 7**, with flag syntax verified against current
llama.cpp. Don't copy a sketch from this document — it will drift.

Two gotchas worth stating once: `LLAMA_CACHE` (llama.cpp's `-hf` downloader) and `HF_HOME` (the
`hf` CLI) are **separate caches**, so pre-warm with `llama-server -hf` or you'll download
everything twice. And llama.cpp flags move — `--no-mmap` and bare `--flash-attn` are both gone.
Check `llama-server --help` before trusting any config you find online, including older drafts of
this one.

**Not chosen, and why:** **vLLM** supports sm_75 at minimum level but has no BF16 on Turing and
wants the whole model in VRAM — its value is high-concurrency batched serving and 8 GB is the wrong
shape for it. **Ollama** is the easiest possible start but abstracts away exactly the knobs
(`-ot`, `--numa`, expert placement) that make this hardware interesting.

---

## Model shortlist

Sizes are Q4_K_M GGUF unless noted. Estimated tok/s are **napkin math from bandwidth ceilings,
discounted for AVX2-only CPU kernels — hypotheses to falsify in Phase 4, not promises.**

**Revised for 64 GB.** Total RAM is now the binding constraint, and **32 GB per NUMA node** is the
number that decides whether a model can be socket-pinned (the fast path — see Phase 4).

| Model | Size | Active params | Where it lives | Est. tok/s | Job |
|---|---|---|---|---|---|
| **Qwen3.6-35B-A3B** | 22 GB | 3B (8 of 256 experts + 1 shared) | **Fits one 32 GB NUMA node** | **10–18** | ★ `coder`. 262K context, pitched at agentic coding. Now clearly the centrepiece of this build |
| **Qwen3.5-9B** | ~5.5 GB | dense, all 9B | **100% in VRAM** | **35–50** | ★ `scorer`. Unaffected by the RAM loss |
| gpt-oss-20b | 12 GB | ~3B | Mostly GPU, some experts on CPU | 20–35 | Fallback `coder`; also the easiest MoE-offload demo |
| Qwen3.6-35B-A3B **Q8** | 37 GB | 3B | Straddles both nodes | ~8–14 | Uses the spare headroom for a quality bump. Costs socket pinning |
| **gpt-oss-120b** | 61 GB (MXFP4) | ~5B | ❌ **Blocked until upgrade A1** | — | Doesn't fit in 64 GB. The hero demo, deferred |
| Qwen3.6-27B | ~17 GB | dense, all 27B | Won't fit VRAM; every param read per token | 2–4 | Skip. Dense models punish you here |

### What 64 GB actually costs you

**The good news first: all three real use cases are unaffected.** Claude Code runs on
Qwen3.6-35B-A3B (22 GB), the resume scorer runs on Qwen3.5-9B entirely in VRAM, and Aider shares
the `coder` model. Nothing in the *working* plan needed 128 GB.

**What you lose is the hero demo.** gpt-oss-120b is ~61 GB of weights; with 64 GB total and an OS
in the way, it doesn't fit. Options, honestly ranked:

1. **Accept it and make the upgrade the payoff.** The 120b run becomes the reward for upgrade A1
   rather than something that works on day one.
2. **mmap from disk instead of loading to RAM.** llama.cpp can page weights on demand, so a model
   larger than RAM technically runs. On the 8 TB spinning disk this will be unwatchable — random
   4K-ish reads of expert weights on every token. On an **NVMe** (upgrade C, ~$25 for the adapter)
   it becomes merely slow instead of impossible. This is now the strongest argument for the NVMe.
3. **A smaller MoE in the 30–45 GB band.** Uses the headroom without going over. Worth a look when
   you're picking models, but nothing in the current shortlist lands cleanly there.

**Practical ceiling:** budget ~50 GB for a model, leaving room for the OS, page cache, and llama.cpp's
own buffers. And for anything you want socket-pinned, the real limit is **~28 GB** — under one
node's 32 GB with headroom.

The headline result: **dense 27B is slower than sparse 120B on this machine.** Active parameters, not total parameters, set the speed.

### The 8 GB / 64 GB trick
Modern MoE models activate a small fraction of their weights per token. Attention layers and the
KV cache are small, hot, and latency-sensitive — perfect for the GPU. Expert weights are huge,
cold, and touched sparsely — tolerable in system RAM. So:

```bash
-ngl 999 --n-cpu-moe 40    # everything to GPU, then push expert layers back to CPU RAM
```

The 2080 handles attention and prompt processing; 64 GB of cheap DDR4 holds the ~22 GB of
Qwen3.6-35B-A3B's experts. Neither component could do this alone. That is the build *today*.

> **Two pending changes make this section temporary.** Upgrade A1 (128 GB) restores the headroom
> for gpt-oss-120b's 61 GB of experts, which is the more dramatic version of this trick. And if
> the 1660 Supers pool enough VRAM to hold a model outright, `--n-cpu-moe` goes to **zero** and the
> trick stops being necessary at all for `coder` — the experts move from 68 GB/s DDR4 to
> 336+ GB/s VRAM. Re-tune after either change.

---

## Use case 1 — Claude Code (set expectations first)

### Wiring it up
`llama-server` speaks `/v1/messages` natively, so this is four environment variables:

```bash
export ANTHROPIC_BASE_URL=http://homelab.lan:8080
export ANTHROPIC_AUTH_TOKEN=local          # any non-empty string
unset ANTHROPIC_API_KEY                    # unset, not set-to-empty
export ANTHROPIC_MODEL=coder
export ANTHROPIC_SMALL_FAST_MODEL=coder    # or point at a smaller model for the cheap calls
claude
```

`ANTHROPIC_AUTH_TOKEN` — not `ANTHROPIC_API_KEY` — is the correct variable when pointing at a
third-party base URL. Leaving `ANTHROPIC_API_KEY` set is the #1 way this silently fails: Claude Code
will happily use it against Anthropic's real API and you'll wonder why the local box is idle.
Put these in a wrapper script (`local-claude`) rather than her shell profile, so her real Claude
Code still works.

### Telling Claude Code the real context size — you must, and there's exactly one knob

**Claude Code assumes 200,000 tokens for any model it doesn't recognize.** Its context-window
lookup fails for gateway model IDs and falls back to that hardcoded default. `coder` gives each
request **131072** (`-c 131072` with `-np 1`).

That mismatch is a live bug, not a rounding error. Auto-compaction fires at roughly 83.5% of what
Claude Code *believes* the window is — about 167k tokens — but llama.cpp hits its wall long before.
You get a hard error, or worse, llama.cpp silently context-shifts and drops the oldest tokens.
The conversation quietly loses its beginning and nobody is told.

**The fix is one variable:**

```bash
export CLAUDE_CODE_AUTO_COMPACT_WINDOW=98304     # 75% of per-slot, NOT the ceiling
```

Two rules, and the second one cost an afternoon to learn:

**1. The budget is usable context *per slot*, not `-c`.** `-c` is the total KV allocation and `-np`
divides it between server slots. Get this backwards and you fail on the first turn:
`-c 65536 -np 2` leaves only 32768 per slot →
`request (32912 tokens) exceeds the available context size`.

**2. ⚠️ It must sit *below* the per-slot ceiling, not equal to it.** Setting the compaction budget
to exactly the hard limit deadlocks: compaction fires with no room left to run in, and `/compact`
is itself a request that has to fit inside the window it's trying to free.

```
API Error: 400 request (65873 tokens) exceeds the available context size (65536 tokens)
Error during compaction: 400 request (66585 tokens) exceeds the available context size (65536)
```

**Nothing recovers from this on its own.** Claude Code's reactive compaction matches "prompt too
long" against Anthropic's error wording, and llama.cpp's phrasing isn't in that set — so the
overflow is never recognised as one. The proactive threshold is the only protection there is.

Hence `-np 1` for `coder`: same `-c`, same VRAM, but the single slot gets all 131072 rather than
half, and the window is set to **75% of that (98304)** to leave compaction somewhere to work. The
cost is that concurrent `coder` requests serialise — a fair trade for two occasional users.

> **Gotcha that made this hard to diagnose:** `local-claude` *exports* these values, so they
> override anything you set in your shell beforehand. Testing a different window by exporting it
> and then running the wrapper silently does nothing.

Documented as: *"Set the context capacity in tokens used for auto-compaction calculations. Defaults
to the model's context window, 200K for standard models… The value is capped at the model's actual
context window."* Since Claude Code thinks the window is 200K, a lower value applies cleanly.
`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` is then a percentage *of this value*, so the default ~83.5% puts
compaction around 54k and leaves ~11k of headroom for the response.

**Keep this number, `-c`, and `-np` in sync.** If you change the server's context or slot count,
recompute: window = 75% of (`-c` / `-np`). It's the single most likely thing to drift out of alignment in
the whole setup.

> **Gateway model discovery does not solve this**, though it looks like it should.
> `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` makes Claude Code query `GET /v1/models` at
> startup — but it reads only `id` and `display_name`. **There is no context-window field in the
> discovery response.** It also *ignores any entry whose `id` doesn't begin with `claude` or
> `anthropic`*, so `coder`, `scorer` and `small` are filtered out entirely. If you want them in the
> `/model` picker, rename them `claude-coder` and friends in the llama-swap config — but you'd
> still need `CLAUDE_CODE_AUTO_COMPACT_WINDOW` for the context size.

### Three more gateway gotchas worth pre-empting

- **Adaptive thinking may 400.** Claude Code treats unrecognized model names — gateway aliases like
  `coder` — as current models and sends `thinking: {"type": "adaptive"}`. If llama-server rejects
  it, set `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1`.
- **Beta body fields may 400.** `context_management` and beta tool schema fields (`strict`,
  `defer_loading`) are sent to any Anthropic-format endpoint. `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`
  turns them off if you see `Extra inputs are not permitted`.
- **Token counting is worth having.** llama-swap serves `/v1/messages/count_tokens`. Without it
  Claude Code estimates context usage locally, which makes the compaction threshold approximate on
  a window this tight. Keep it working.

One piece of good news for the prompt-processing bottleneck: from Claude Code v2.1.181 the system
prompt attribution block is **stable for the lifetime of a conversation** behind a custom base URL.
That means llama.cpp's prefix KV cache actually gets reused between turns instead of being
invalidated by a changing prefix. On older versions, set `CLAUDE_CODE_ATTRIBUTION_HEADER=0`.

### Honest expectations — read this before you set it up for her

This is the part where a homelab plan usually oversells. It shouldn't.

- **Prompt processing, not generation, is the bottleneck.** Claude Code sends a large system
  prompt plus every tool definition on every turn, and reads whole files into context. On a
  hybrid GPU+CPU MoE setup, prefill of tens of thousands of tokens is where the seconds go. Expect
  multi-second — sometimes tens of seconds — pauses before the first token on a long turn. Raising
  `-b`/`-ub` to 4096 helps; nothing eliminates it.
- **Tool-calling reliability is the real gap.** Local models are meaningfully worse at Claude
  Code's agentic loop than Claude is — malformed tool calls, giving up early, editing the wrong
  file. Qwen3.6-35B-A3B is the strongest local candidate specifically because it's tuned for
  agentic coding, but the gap is real and no amount of hardware closes it.
- **KV cache is the VRAM killer.** 131K context is not free. `--cache-type-k q8_0
  --cache-type-v q8_0` roughly halves KV memory for a small quality cost and is basically
  mandatory here. If it OOMs, drop `-c` before you drop `--n-cpu-moe`.
- **Frame it correctly.** This is a genuinely useful privacy-preserving option for working on
  things she doesn't want leaving the house, and a great demo. It is not a replacement for real
  Claude Code on real work, and telling her that up front will go better than letting her discover
  it.

### Two users at once
If she's running Claude Code while you're running Aider against the same `coder` model, `-np 2`
gives the server two parallel slots — but they **share** the `-c` context budget (so `-c 131072
-np 2` is 64K each). If both of you are doing heavy agentic work, define two llama-swap entries
pointing at the same GGUF with different context sizes, or accept the serialization.

---

## Use case 2 — Resume ↔ JD fitness scoring (the box's best workload)

This is the one where the hardware is genuinely well-matched: batch, latency-irrelevant, short
structured outputs, and *many* repeats. And the 20 cores and GPU that go to waste on a single
interactive stream get used properly, because llama-server batches across parallel slots.

### Serving config
```bash
llama-server -m /srv/models/Qwen3.5-9B-Q4_K_M.gguf \
  -ngl 999 -c 16384 -np 8 --seed 42 --temp 0
```
`-np 8` is the important flag: throughput on batched short requests scales far better than
single-stream generation, because you're amortizing the same weight reads across 8 sequences. Start
at 8 and tune until VRAM complains.

### Structured output
Don't parse free text. llama.cpp does grammar-constrained decoding, so the model *cannot* emit
invalid JSON:

```json
{
  "json_schema": {
    "type": "object",
    "properties": {
      "evidence":     {"type": "array", "items": {"type": "string"}},
      "gaps":         {"type": "array", "items": {"type": "string"}},
      "score":        {"type": "integer", "minimum": 0, "maximum": 100},
      "confidence":   {"type": "string", "enum": ["low", "medium", "high"]}
    },
    "required": ["evidence", "gaps", "score", "confidence"]
  }
}
```

Note the field order: **evidence and gaps come before the score.** Forcing the model to enumerate
its reasoning before committing to a number measurably improves scoring quality — and grammar
constraints generate fields in schema order, so the schema is what enforces it. The native
`json_schema` field on llama.cpp's `/completion` endpoint is the reliable path; `response_format`
on the OpenAI-compatible `/v1/chat/completions` has had bugs historically — verify it works on your
build before depending on it.

### Making the A/B actually mean something

"A/B" here means two arms — two prompt versions, or two models — over the same inputs. Two things
will otherwise sink it:

1. **LLM scores have high run-to-run variance, even at `--temp 0`.** A single score per pair is
   noise. Run each (resume, JD) pair **N=5+ times per arm** and compare distributions, not points.
   Report median and spread. If arm A and arm B's spreads overlap, you have not measured a
   difference. This is the single most common way homebrew LLM evals mislead their authors.
2. **`--temp 0` is not determinism.** llama.cpp with a fixed `--seed` and identical batch settings
   is *reasonably* reproducible on the same binary and hardware, but batching, `-np`, and slot
   scheduling all perturb results. Pin `--seed`, keep `-np` constant across arms, and verify by
   running the same input twice before trusting anything.

Design notes that matter more than the model choice:
- **Build a golden set first.** 20–30 (resume, JD) pairs where *you* have decided the right answer.
  Without labels you're measuring self-consistency, not accuracy.
- **Measure agreement with a reference, not just self-agreement.** Score the golden set with real
  Claude via the API once, treat that as the reference arm, and report rank correlation
  (Spearman) between local and reference. Absolute scores from local models are compressed toward
  the middle; *ranking* is what survives.
- **Watch for position and length bias.** Longer resumes score higher for no good reason. Include
  a deliberately padded resume in the golden set as a control.
- **Log everything**: model, quant, seed, prompt hash, schema hash, `-np`, timestamp, raw JSON.
  Off the box entirely — not the 8 TB. This is the actual research output, and it's the one thing
  here that isn't re-downloadable.

Runtime estimate: 30 pairs × 2 arms × 5 repeats = 300 requests. At ~2K prompt / ~300 output tokens
each with `-np 8`, that's a coffee break, not an overnight run. You can afford far more repeats
than you think — use them.

---

## Use case 3 — Aider (the easy one)

Aider routes through LiteLLM, which needs the `openai/` prefix to recognize an OpenAI-compatible
endpoint:

```bash
export OPENAI_API_BASE=http://homelab.lan:8080/v1
export OPENAI_API_KEY=local
aider --model openai/coder --edit-format diff
```

Two things worth setting:

- **Edit format.** `diff` is token-efficient but demands precise search/replace blocks; weaker
  local models fail it and thrash. If you see repeated "SEARCH block not found" errors, fall back
  to `--edit-format whole` — much more reliable, much more token-hungry. Try `diff` first.
- **Model metadata.** Aider doesn't know your local model's context window, so it can't manage the
  repo map budget. Declare it in `.aider.model.settings.yml`:

```yaml
- name: openai/coder
  edit_format: diff
  use_repo_map: true
  extra_params:
    max_input_tokens: 131072
```

Since Aider already speaks the Anthropic API too, the same `ANTHROPIC_BASE_URL` trick from use
case 1 works if you'd rather keep one dialect — but the OpenAI path is better-trodden in Aider.

---

## Choosing the distribution

Four constraints decide this, and they point the same direction:

| Constraint | What it rules in / out |
|---|---|
| **ZFS with `copies=2`** for the failing 8 TB | ZFS is out-of-tree everywhere. The distro that ships it **prebuilt** rather than via DKMS wins |
| **NVIDIA driver + CUDA toolkit** to build llama.cpp | You're compiling with `-DGGML_CUDA=ON`. Toolchain friction is a real, recurring cost |
| **Household service, two users** | LTS. Not rolling. Boring is a feature |

### Recommendation: Ubuntu LTS Server, headless

**The tiebreaker changed in April 2026.** Ubuntu 26.04 LTS ("Resolute Raccoon") is the first Ubuntu
to ship **NVIDIA CUDA natively in the archive** — `sudo ubuntu-drivers install` pulls a
repo-managed driver that participates in normal updates, and CUDA 13.3 builds against the shipped
GCC 15 with no `-ccbin` workaround. On a box whose whole point is compiling llama.cpp with CUDA,
that removes the single most annoying recurring chore. Support runs to 2031 standard / 2036 ESM.

**The ZFS argument points the same way, for a different reason.** Ubuntu ships the ZFS kernel
module **prebuilt and signed** in `linux-modules-extra`; Debian builds it locally with DKMS on
every kernel update. DKMS is fine until the day it isn't — a failed rebuild after a kernel bump
means your pool doesn't import, on the machine holding your model library. Canonical building and
signing it for you is worth real money here.

**Which LTS, though —** and this is a live question as of **2026-07-31**:

| | Ubuntu 24.04 LTS | Ubuntu 26.04 LTS |
|---|---|---|
| Age | Mature, boring, thoroughly de-bugged | ~14 weeks old |
| CUDA | Add NVIDIA's repo manually | **Native in the archive** |
| Kernel | Well-trodden with ZFS | 7.0 — newer than most ZFS testing |
| Support | to 2029 / 2034 ESM | to 2031 / 2036 ESM |
| Risk | Known quantity | 26.04 removed SHA-1 module signing; out-of-tree modules need the new scheme |

**Take 26.04 LTS, but wait for 26.04.1.** Ubuntu LTS point releases land roughly three months
after the initial release (24.04.1 was late August 2024), so **26.04.1 is due within weeks** of
this writing. That's a cheap way to skip the early-adopter tax on a kernel-7.0-plus-out-of-tree-ZFS
combination. If you want to start building today rather than in September, 24.04 LTS is entirely
defensible — you'll add NVIDIA's CUDA repo by hand and lose nothing else.

**Verify ZFS before you trust it, whichever you pick:**
```bash
apt install zfsutils-linux
modinfo zfs | grep -E 'filename|version|sig'   # want a path under /lib/modules/.../kernel/, not dkms
zpool status                                   # after every kernel update, before you walk away
```
Keep a known-good kernel in the GRUB menu and don't blind-reboot after a kernel bump.

### Why not the alternatives

- **Debian 13 (Trixie)** — the credible runner-up, and the right pick if you'd rather not have
  snaps or Canonical in the loop. Costs: ZFS via DKMS (see above), and manual NVIDIA/CUDA
  packaging. Everything else is equivalent.
- **Proxmox VE** (Debian-based) — ZFS is first-class and built in, which is genuinely tempting.
  But it's a hypervisor, and GPU passthrough on a 2016 board means wrestling IOMMU groups and ACS
  quirks with engineering-sample CPUs. That's exactly the yak-shave that kills homelab projects.
  **Bare metal now; revisit Proxmox only if this box grows a second job.**
- **Fedora / RHEL / Rocky** — Fedora's fast-moving kernel plus out-of-tree ZFS is a recurring
  breakage generator; avoid it specifically because of the storage plan. RHEL/Rocky 10 are stable
  but ZFS is still out-of-tree and the older userspace makes CUDA builds fiddlier.
- **Arch** — the AUR has everything, but a rolling release under a service other people depend on
  is a 2 a.m. outage waiting to happen. No.
- **NixOS** — genuinely excellent here (declarative, first-class ZFS, reproducible rebuilds, easy
  rollback). The learning investment is real. Worth it if you already want to learn Nix; a
  distraction if you don't.
- **TrueNAS SCALE** — ZFS-native, but it's a storage appliance. Running llama.cpp and Docker under
  it means fighting the design.

### Setup notes that follow from the choice

- **Headless.** No desktop, no Wayland, no GNOME. `ubuntu-server` minimal install.
- **Docker from Docker's own repo**, not the snap. The snap's confinement makes bind-mounts and
  GPU access needlessly painful for Open WebUI.
- **`unattended-upgrades` for security patches, but pin the kernel** or at least never let it
  reboot unattended — a kernel bump that breaks the ZFS module takes the model library offline.
- **`intel-microcode` will no-op** on your ES CPUs. Harmless; it'll log and move on. Leave it
  installed for the day you fit retail chips.
- **x86-64 baseline:** Broadwell-EP is `x86-64-v3` (AVX2, FMA, BMI2), which every current distro
  targets — RHEL 10's v3 baseline included. If a future distro ever moves to `x86-64-v4`
  (AVX-512), this box is excluded. Nothing mainstream has, but it's the clock on the platform.

---

## Build

> **The step-by-step build lives in `HOST_SETUP.md`** — 10 phases, every command verified against
> current upstream docs. This section keeps only the *tuning* work, which is analysis rather than
> setup and belongs with the reasoning.

### Tuning the MoE offload
Start with gpt-oss-20b to get the mechanics right, then move to `coder`.

```bash
# 20b — learn the flags here
llama-server -hf ggml-org/gpt-oss-20b-GGUF \
  -c 16384 -ngl 999 --n-cpu-moe 22 -fa on -b 2048 -ub 2048 --temp 1.0 --top-p 1.0

# Qwen3.6-35B-A3B — the daily driver, pinned to one socket
numactl --cpunodebind=0 --membind=0 \
  llama-server -hf unsloth/Qwen3.6-35B-A3B-GGUF \
  -c 32768 -ngl 999 --n-cpu-moe 40 -fa on --load-mode none
```

Tune `--n-cpu-moe` **downward** until you OOM, then back off by 2. Lower = more experts on the
GPU = faster. The right value is hardware-specific; there is no correct number to copy from a blog.

MXFP4 is natively quantized — do not re-quantize gpt-oss. Turing has no native MXFP4 support;
llama.cpp dequantizes on the fly and it works fine. Sampling for gpt-oss: `--temp 1.0 --top-p 1.0`,
no repetition penalty.

**If you fit the 1660 Supers (Upgrade B), re-run this from scratch.** With enough pooled VRAM to
hold the model, `--n-cpu-moe` should go to **zero** and this entire tuning exercise becomes moot —
which is the point.

### NUMA tuning (the interesting part)
llama.cpp does not handle NUMA gracefully; letting it sprawl across both sockets is often *slower*
than confining it to one. Benchmark the same model four ways with `llama-bench`:

| Config | Command prefix | Hypothesis |
|---|---|---|
| Naive | *(none)* | Baseline. Threads and pages land wherever |
| Interleaved | `numactl --interleave=all` + `--numa distribute` | Uses both sockets' bandwidth, pays QPI latency |
| Socket-pinned | `numactl --cpunodebind=0 --membind=0` | **Fastest for anything that fits in one 32 GB node** |
| Socket-pinned, GPU-adjacent | pin to whichever socket owns the 2080's PCIe root | Best of all — cuts a QPI hop off every GPU transfer |

Find the GPU's socket: `cat /sys/bus/pci/devices/<gpu-bdf>/numa_node`. Set `-t 10` (physical cores
on one socket) when pinned, not `-t 40`. Also try `--load-mode none` — it forces the model fully
into RAM up front and removes page-fault jitter during generation, at the cost of a slow start.

**✅ Measured 2026-08-02.** The RTX 2080 is at `0000:02:00.0` and reports **`numa_node = 0`**, so
node 0 is the pinning target. Two refinements from the real topology:

- **The nodes are not the same size:** node 0 = 31,810 MB, node 1 = 30,148 MB. Size a
  socket-pinned model against **30 GB**, not a flat 32.
- **⚠️ Unpinned runs really do sprawl.** A baseline taken mid-run showed node 1 down to **293 MB
  free** while node 0 still had 15 GB. That's the allocator spilling exactly as feared, and it's
  the strongest argument for pinning that this box has produced so far. `numastat -m` while a model
  is loaded will show you whether the pin is actually holding.

**Expected result:** Qwen3.6-35B-A3B (22 GB) fits inside one 32 GB node and should get meaningfully
faster when pinned. **Note this is now a tighter fit than originally planned** — at 128 GB each
node held 64 GB; at 64 GB each holds 32, so a 22 GB model plus buffers leaves little slack. Watch
for the allocator spilling across nodes and silently undoing the pinning.

The two-models-with-opposite-optimal-configs comparison needs gpt-oss-120b, so it waits for
upgrade A1.

### The eval harness
Golden set → schema → runner → results synced off-box. See use case 2. Do this last; it's the
only phase where the *methodology* matters more than the config.

---

## Overnight work — using the rig while it's idle

The box is sized for interactive use by two people, which means it's asleep sixteen hours a day.
Everything below is batch, latency-irrelevant, and unattended — exactly what this hardware is good
at and exactly what it can't do while someone's waiting on a token.

Ranked by value to *this* build:

### 1. The resume ↔ JD eval sweep — the obvious one

Use case 2 is already batch-shaped and its main constraint is that meaningful A/B testing needs
*many* repeats. Overnight removes the reason to skimp. 30 pairs × 2 arms × 5 repeats is a coffee
break; **30 × 4 arms × 25 repeats is an overnight run** and gives distributions you can actually
defend. Run with `-np 8` and let it grind.

This is the single highest-value use of idle time, because sample size is the thing standing
between "I have a hunch" and "I measured it."

### 2. Fill the benchmark table automatically

The NUMA matrix and the multi-GPU ladder are ~15 `llama-bench` invocations that each take minutes.
Script it, run it once a night, append to CSV. You get the table filled in without an evening of
babysitting, and you get a time series that catches regressions after kernel or llama.cpp updates.

### 3. Transcribe the back-catalog

You have a YouTube series and no transcripts. Overnight ASR gives you subtitles, searchable
searchable text, and chapter markers — and it's the rare workload where this box's
weakness (memory bandwidth) doesn't matter at all.

**Use `faster-whisper`, not `whisper.cpp`, on this hardware.** Its CTranslate2 CUDA backend is
better optimised than whisper.cpp's CUDA path on NVIDIA. `large-v3-turbo` is ~1.6 GB at INT8 and
roughly 7× faster than `large-v3` for a small accuracy cost — so it coexists with a resident LLM
in 8 GB, or runs alongside on one of the 1660 Supers once they're fitted.

### 4. Quantization bake-off with `llama-perplexity`

Run Wikitext-2 perplexity across Q4_K_M / Q5_K_M / Q8_0 of your actual models and settle "which
quant should I use" with your own numbers instead of forum folklore. Lower is better; the
comparison is only valid within one model family on one dataset. Genuinely good content, and it
tells you whether the VRAM you're spending on Q5 buys anything.

### 5. Everything else worth queuing

- **RAG index builds** — embed transcripts and docs for Open WebUI.
- **Model prefetch** — 61 GB of gpt-oss-120b over a domestic link is an overnight job by itself.
- **Synthetic data** — generate JD variants and edge-case résumés to grow the eval golden set.

### Scheduling notes that will save you a bad night

- **Use systemd timers, not cron** — consistent with the rest of the box, and `journalctl` gives
  you the failure history.
- **⚠️ Batch jobs and llama-swap fight over VRAM.** Anything that loads a model directly
  (`llama-bench`, `llama-perplexity`, faster-whisper) is a second model server by another name.
  Either drive the work *through* llama-swap's endpoint, or `systemctl stop llama-swap` at the top
  of the job and start it again at the end. This is the same trap that got Lemonade cut.
- **Mind the TTL.** A model with `ttl: 3600` unloads after an idle hour. A long batch run that
  pauses between phases can pay a full reload; either keep the requests flowing or raise the TTL
  for the job's duration.
- **Don't collide with maintenance.** The monthly ZFS scrub and the ~12-hour SMART long test are
  already overnight jobs, and the scrub on a failing 8 TB drive is not something to run under load.
- **Power and noise are real.** Idle is ~150–200 W; under sustained load expect meaningfully more,
  every night, in a house where people sleep. Measure it before committing to a nightly schedule,
  and consider whether "every night" should really be "twice a week."
- **Send results off-box.** Nothing on this host is durable: the 8 TB is a failing disk holding
  re-downloadable models, and the boot SSD is a 120 GB budget drive. An unattended job that writes
  only locally is one disk failure from having produced nothing. Sync to wherever you keep things.

---

## Things that will bite you

1. **`ANTHROPIC_API_KEY` left set.** Claude Code silently uses real Anthropic instead of your box.
   Check `echo ${ANTHROPIC_API_KEY-unset}` when debugging "why is this so fast?" — and `unset` it
   rather than setting it empty, since a blank value can still win credential resolution.
2. **KV cache is the silent VRAM killer.** A 7B at Q4 is ~4.7 GB of weights, but 32K of context
   adds ~4 GB of KV cache — instant OOM on an 8 GB card. Budget context explicitly; use
   `--flash-attn` (Turing supports it) and quantized KV cache.
3. **AVX2 only.** Broadwell-EP predates AVX-512 and AMX. Benchmarks from Sapphire Rapids or
   Granite Rapids Xeons are not comparable — those chips have dedicated matrix units yours lacks.
4. **Dual-socket is not 2× anything** for this workload. It's 2× capacity and roughly 1× useful
   bandwidth, plus a latency tax.
5. **DDR4-2133 is the floor of the DDR4 range.** Nothing to do about it with 16 slots populated,
   but your 68 GB/s is the pessimistic end of quad-channel DDR4.
6. **Idle power.** Two 85 W CPUs, 16 DIMMs, a 215 W GPU and an 8 TB spinner — expect roughly
   150–200 W idle, $20–35/month depending on rate. This matters more now that it's a service two
   people depend on: it has to actually stay on. Measure it with a wall meter — it's the honest
   counterweight to "free local AI," and it's the number most write-ups leave out.
7. **Noise and heat.** A dual-socket workstation board under sustained 100% CPU for minutes at a
   time is a different acoustic experience than gaming. Plan where it lives — especially if it's
   now always-on for household use.
8. **Don't re-quantize MXFP4 models.** gpt-oss ships natively quantized. Converting it to Q4_K_M
   makes it bigger *and* worse.
9. **Don't flash the BIOS.** With ES CPUs, a firmware update can drop the microcode your chips
   need and leave the board unable to POST. Highest-consequence, lowest-benefit action available
   to you on this machine.
10. **Filling all 16 DIMM slots downclocks the memory bus.** ASUS's footnote is explicit that
    RDIMMs only hit top speed at 1 DIMM per channel, and owners of this board report 1866 MT/s
    with all 16 populated. On a bandwidth-bound workload that's a real double-digit loss. The fix
    is fewer, denser DIMMs — never more of them.
11. **`Speed` ≠ `Configured Memory Speed` in `dmidecode`.** The first is what the module is rated
    for; only the second tells you what the bus is actually running at. Don't diagnose memory
    performance from the label on the stick.

---

## Upgrade paths

> 💸 **Prices below are a snapshot from 2026-07-31 and will be wrong soon.** Used GPU and DDR4
> pricing swings hard month to month — driver EOLs, new-generation launches, datacenter
> decommissions dumping used stock, tariffs, and memory-market cycles all move these numbers by
> tens of percent. The 3090 in particular has been a volatile line for years. **Re-check current
> street prices before buying anything, and re-check the ordering of the ladder too** — the
> *ranking* of these upgrades depends on price, so a swing big enough can reorder them. The
> reasoning (which bottleneck each upgrade attacks) is durable; the dollar figures are not.

Two different bottlenecks, two different upgrades. Buying the wrong one is the expensive mistake:

| Symptom | Bottleneck | The upgrade that fixes it |
|---|---|---|
| Long pause before the first token in Claude Code | **Prompt processing** — GPU compute + VRAM | More/bigger GPU |
| Tokens trickle out once it starts | **Memory bandwidth** — DDR4-2133, CPU-side experts | Faster RAM |
| "Model won't fit" | VRAM or system RAM capacity | Depends which |

For use case 1 (Claude Code) the GPU is the lever. For use cases 2/3 and the gpt-oss-120b hero
demo, **memory is the lever, and it's the cheaper one.** Most people buy the GPU first. On this
box that's backwards.

### First, get the actual slot facts off the machine

ASUS's spec sheet says **six physical x16 slots: four running x16 electrical, two running x8.**
Your recollection of "four x16" is right — those are the full-width ones. Published sources
disagree on the slot-to-CPU mapping (three published sources contradict each other, most of them
describing a different Z10PE variant), so don't trust a spec sheet here. Ask the board:

```bash
lspci -tv                                            # topology tree
lspci -vv | grep -E 'LnkCap|LnkSta'                  # negotiated vs capable width per slot
for d in /sys/bus/pci/devices/*/; do
  echo "$(basename $d) numa_node=$(cat $d/numa_node 2>/dev/null)"
done
```

That last one is the important one: it tells you **which socket owns each slot**, which decides
where the GPU goes (Phase 4) and which slots die if you ever run one CPU. ASUS's own FAQ confirms
that with CPU1 only, just slots 2/3/4 are live — so anything you install in the CPU2-side slots
makes the second CPU non-optional.

### The blocked top slot

You've got the board in front of you and I don't, so I'm taking the clearance problem as given.
Design around it: **put a short card in the blocked slot** — an NVMe adapter, a 10GbE NIC, or an
SSD carrier. Save the long full-width slots for GPUs.

One thing worth five minutes with the side panel off: check whether the obstruction is the DIMM
*slots* themselves or the *installed modules* standing ~30 mm proud of them. If it's the modules,
the memory upgrade below — which drops you from 16 DIMMs to 8 — may empty that bank and free the
slot as a side effect. Pull the DIMMs in that bank and dry-fit a long card before you decide the
slot is unusable.

### Upgrade A — Memory: the highest-leverage change, and cheaper than I first thought

**Do the `dmidecode` check in the Memory compatibility section before reading further.** The whole
sizing of this upgrade depends on whether you're at 1866 or 2133 today.

Token generation is bandwidth-bound, and **fewer, denser DIMMs beats more, smaller ones** on this
board — because RDIMMs only hit their top speed at 1 DIMM per channel. You have 16 DIMMs on 8
channels. Going to 8× 16 GB keeps the capacity, halves the DIMM count, and buys back the
downclock. There are two versions:

**A1 — the cheap, safe one: 8× 16 GB DDR4-2133, keep your existing CPUs.**

No CPU swap, no BIOS risk, no ES complication, no retail-microcode gamble. Just eight modules.
The QVL validates **Samsung M393A2G40DB0-CPB** (16 GB, DDR4-2133 ECC/REG CL15, 2 rank) — same
family as what you already own. Used 16 GB DDR4-2133 RDIMMs are among the cheapest server parts in
existence.

**A2 — the bigger one: 8× 16 GB DDR4-2400 + 2400-capable retail Xeons.**

E5-2630 v4 tops out at 2133; E5-2650 v4 and E5-2680 v4 do 2400. The QVL validates
**M393A2K40BB1-CRC** (16 GB DDR4-2400, 1 rank) and **M393A2G40EB1-CRC** (16 GB DDR4-2400, 2 rank).

| | Now (likely) | A1 | A2 |
|---|---|---|---|
| Config | 16× 8 GB, 2 DPC | 8× 16 GB, 1 DPC | 8× 16 GB, 1 DPC |
| CPUs | ES E5-2630 v4 | **unchanged** | retail 2650/2680 v4 |
| Speed | 1866 MT/s | 2133 MT/s | 2400 MT/s |
| Per-socket BW | ~59.7 GB/s | ~68.3 GB/s | ~76.8 GB/s |
| Est. gain in tg | — | **~+14%** | **~+29%** |
| Rough cost | — | **~$80–120** | ~$200–300 |
| Risk | — | **essentially none** | ES→retail microcode gamble |

**A1 is now the clear #1 upgrade, and its value has changed.** It started as a ~14% speed tweak.
After the 128 GB build failed, it's the thing that **restores your lost capacity** — 8× 16 GB
gives you the full 128 GB *at 1 DIMM per channel*. Three reasons, in order of certainty:

- **Capacity (certain):** 64 → 128 GB, which unblocks gpt-oss-120b and the hero demo
- **Reliability (well-evidenced):** eight modules and eight slots instead of sixteen — half the
  failure surface, on a board that has already proven it has faults in that surface. You also get
  to qualify the new sticks in slots you've verified good
- **Speed (documented, unmeasured here):** staying at 1 DPC should hold 2133, where a 16× 8 GB
  build would likely drop to 1866. That's ASUS's footnote and other owners' reports — not
  something this machine has shown, since the 16-DIMM config never ran

You can also qualify the new sticks in the eight slots you've already proven good, which makes it
a low-risk purchase rather than another evening of bisecting.

Side effects either way: 8 free DIMM slots, better airflow, lower idle draw, and possibly an
unblocked top PCIe slot if the obstruction turns out to be the modules rather than the sockets.

⚠️ **The ES complication applies only to A2.** Retail CPUs need BIOS microcode that a board running
ES silicon may not carry — and getting it could require the BIOS update you were just told not to
do. **Buy one retail CPU, test it solo in socket 1, then buy the second.** Never run one ES and one
retail chip as a permanent config. Budget an evening, not ten minutes.

> **The LRDIMM escape hatch, for completeness:** ASUS's footnote says LR-DIMMs hit 2400 *at any*
> DPC — so 16 slots at full speed is technically possible. But the QVL's LRDIMM entries are 32 GB
> and 64 GB parts, so the smallest such build is 512 GB, and LRDIMMs cost roughly double. Wrong
> trade for 128 GB. Noted only so you know why the "just buy LRDIMMs" advice you'll find online
> doesn't apply here.

### Upgrade B — GPU: fixes Claude Code specifically

Adding VRAM lets more expert layers live on the GPU (`--n-cpu-moe` goes *down*), which speeds up
generation, and gives prompt processing more room — which is what actually makes Claude Code feel
usable.

| Option | VRAM | ~Cost | Verdict |
|---|---|---|---|
| **3–4× GTX 1660 Super you already own** | +18–24 GB | **$0** | ★★ **Try this first.** See below — it may be the largest single win available, and it's free |
| **Second RTX 2080** | 8 → 16 GB | ~$150–200 used | Matched cards, no complications. Only worth buying *after* testing the 1660s, which are free and give more VRAM |
| **Used RTX 3090** | 24 GB | ~$800–1000 | Best VRAM/$ on the open market and the enthusiast default. Ampere, has tensor cores. Big, hot, 3× 8-pin — check EEB clearance |
| RTX 5060 Ti 16 GB | 16 GB | ~$550 new | New silicon with a warranty, but less bandwidth and less VRAM than a 3090 for not much less money |
| **Tesla P40 / P100** | 24 / 16 GB | ~$200–300 used | ❌ **Do not buy.** See below |

#### ★ The six GTX 1660 Supers — the free upgrade that might beat all the paid ones

You already own six of these. They are **far more interesting for this build than their reputation
suggests**, for one specific reason.

**They're compatible in every way that matters.** TU116 is **compute capability 7.5 — the same as
your RTX 2080**. Your existing `-DCMAKE_CUDA_ARCHITECTURES=75` build covers them with no changes,
the same driver branch serves both, and Turing was explicitly retained past the 580 cull. Mixed-GPU
layer split in llama.cpp works fine across dissimilar cards.

**The catch is real: no tensor cores.** TU116 substitutes 128 dedicated FP16 cores per SM — 2× the
FP32 rate, but nowhere near tensor-core throughput; llama.cpp contributors have described FP16 on
this die bluntly. Per-card compute is weak.

**But the win isn't compute — it's escaping DDR4 entirely.** Right now `coder`
(Qwen3.6-35B-A3B, ~22 GB) runs with its experts in system RAM at **~68 GB/s**. Pool enough VRAM to
hold the whole model and the same weights get read at **336–448 GB/s**:

| Config | Total VRAM | Fits 22 GB model? | Weight-read bandwidth |
|---|---|---|---|
| 2080 alone | 8 GB | No — experts on CPU | ~68 GB/s (DDR4) |
| 2080 + 2× 1660S | 20 GB | Nearly | mixed |
| **2080 + 3× 1660S** | **26 GB** | **Yes, tight** | **~336–448 GB/s** |
| 2080 + 4× 1660S | 32 GB | Yes, with real KV headroom | ~336–448 GB/s |

That's a **~5× improvement in the quantity that governs token generation**, and it would drop
`--n-cpu-moe` to zero. Prompt processing should improve substantially too — even weak GPU FP16
beats AVX2 CPU experts by a wide margin — though the missing tensor cores mean it won't match what
a 3090 would do.

**Treat those numbers as a hypothesis, not a promise.** Layer-split serialises across cards, PCIe
3.0 adds hops, and nobody benchmarks four 1660 Supers. But the mechanism is sound and the
experiment costs nothing.

**Test incrementally — 2 cards, benchmark, then 3, then 4.** Stop when `llama-bench` stops
improving. Practical constraints to check as you go:

- **Slots:** four x16 + two x8, one physically blocked by RAM for long cards. 1660 Supers are
  usually dual-slot, so realistically **4–5 cards total**, not six.
- **NUMA:** cards hanging off CPU2's PCIe root cross QPI. Check
  `/sys/bus/pci/devices/<bdf>/numa_node` for each and keep pinning consistent.
- **Power:** ~125 W each. 2080 + 4× 1660S + 170 W of CPU ≈ 900 W. The 1200 W PSU covers it, but
  count your 8-pin connectors before ordering nothing.
- **Heat and noise:** five cards in an EEB chassis is an airflow problem, and this box is meant to
  be always-on for household use.
- **Flags:** `--split-mode layer` (default), `--tensor-split 8,6,6,6` to match VRAM, `--main-gpu`
  on the 2080 so the KV cache sits on the fastest card.

**If this works, the ladder changes completely** — the second 2080 becomes pointless and the 3090
becomes a question about prompt processing only.

**The P40 trap.** Half the local-LLM advice online still recommends the Tesla P40 as the budget
24 GB card. That advice is now stale and actively harmful: NVIDIA's **580 driver branch dropped
Maxwell, Pascal, and Volta**, so P40 and P100 get security patches only through Oct 2028 and no new
CUDA features ever. Turing — your 2080 — was explicitly retained. Buying a P40 in 2026 is buying
onto a dead branch, and it would also force your working 2080 onto a legacy driver.

**Multi-GPU notes for llama.cpp on a PCIe 3.0 box:**
- Keep `--split-mode layer` (the default). Cross-card traffic only happens at layer boundaries, so
  PCIe bandwidth barely matters. `--split-mode row` floods the bus and is usually *slower* without
  NVLink.
- Mixed cards work. Use `--tensor-split` to match the VRAM ratio (e.g. `24,8` for a 3090 + 2080),
  and put `--main-gpu` on the biggest card so the KV cache has somewhere to live.
- Expect roughly **1.4–1.6× from a second card, not 2×.** Budget accordingly.
- PCIe 3.0 x16 ≈ 16 GB/s. That mostly costs you model *load* time, not inference speed.
- 1200 W handles two 3090s plus 170 W of CPU with margin. The constraint is physical clearance and
  8-pin connectors, not watts.

### Upgrade C — Storage and network (cheap, do them whenever)

- **NVMe on a PCIe 3.0 x4 adapter** (~$25) in the blocked short slot. This board predates NVMe boot
  in most BIOS revisions, so keep the 120 GB SSD as boot and mount NVMe as a scratch/model-staging
  drive. Affects load times, not inference.
- **10GbE NIC** if the eval harness ever pulls datasets over the network, or if Open WebUI serves
  the household. Also a short card — good candidate for the blocked slot.
- **A third disk, if you'd rather keep results local** than sync them off-box. Optional — the
  design assumes off-box. Eval sets and A/B results are the only things on this box
  that aren't re-downloadable.

### Where to stop

This is a 2016 platform, and honesty about its ceiling belongs in the plan. **Memory bandwidth is
the wall, and it cannot be moved past ~77 GB/s per socket** — no CPU, GPU, or amount of RAM changes
that. For reference: a modern unified-memory box with 128 GB (Ryzen AI Max / Strix Halo class) runs
gpt-oss-120b at roughly **30 tok/s** against this box's estimated 5–10, for maybe $1500–2000.

Which means the sensible ladder is (prices as of **2026-07-31** — see the volatility note at the
top of this section and re-price before buying):

0. **Run `dmidecode` first.** Free. Confirms you're now at 2133 with the 8-DIMM config.
1. **Fit 3–4 of the GTX 1660 Supers you already own.** **$0.** Potentially the biggest single
   win on this list: enough pooled VRAM to hold `coder` entirely on GPU and stop reading weights
   over DDR4. Benchmark after each card. Do this before spending anything.
2. **A1: 8× 16 GB DDR4-2133** (~$80–120) — **restores 128 GB at full speed**, unblocks
   gpt-oss-120b, and halves the number of modules that can fail. Test them in your eight
   known-good slots. This is no longer a tweak; it's the fix for the capacity you lost.
3. **NVMe on a PCIe adapter** (~$25 + drive) — with 64 GB it's the only way to mmap an oversized
   model at tolerable speed, and it fixes model load times regardless.
4. **Second RTX 2080** (~$175) — only if step 1 fails for a reason a matched card would fix. The
   1660s give more VRAM for nothing, so this is hard to justify.
5. **A2: 2400-capable retail CPUs** (~$100 more) — another ~14%. Only after the one-CPU-at-a-time
   microcode test.
6. **Used RTX 3090** (~$900) — only if step 1 worked *and* prompt processing is still the pain
   point. That's the one thing the tensor-core-less 1660s can't fix.
7. **Stop.** Past this, you're spending 3090 money to chase a platform that a ~$1500 mini-PC beats
   on the flagship workload. Spend it on the new box instead — and keep this one, because 20 cores
   and 128 GB of ECC is a perfectly good hypervisor, NAS, and CI runner for another decade.

Steps 1–3 are cheap or free and price-insensitive; 16 GB DDR4-2133 RDIMMs are near the floor of the
used server market. The paid GPU steps are the volatile ones — if used 3090s drop under ~$600, step
6 climbs. **Re-price before committing.** Every figure here is a 2026-08-01 snapshot of a market
that moves; the reasoning about which bottleneck each upgrade attacks is what's durable.

---

## Benchmark methodology

Run `llama-bench` per row. Report prompt processing (pp512) and token generation (tg128)
separately — different bottlenecks (GPU compute vs. RAM bandwidth), and conflating them is how
most local-AI benchmarks go wrong. **For use case 1, pp512 is the number that determines whether
Claude Code feels usable.**

| Model | Quant | Placement | NUMA config | pp512 tok/s | tg128 tok/s | VRAM | RAM |
|---|---|---|---|---|---|---|---|
| Qwen3.5-9B | Q4_K_M | 100% GPU | n/a | | | | |
| Qwen3.5-9B | Q4_K_M | 100% GPU, `-np 8` | n/a | | | | |
| gpt-oss-20b | MXFP4 | `--n-cpu-moe 22` | pinned | | | | |
| Qwen3.6-35B-A3B | Q4_K_M | `--n-cpu-moe 40` | naive | | | | |
| Qwen3.6-35B-A3B | Q4_K_M | `--n-cpu-moe 40` | pinned node 0 | | | | |
| Qwen3.6-35B-A3B | Q4_K_M | `--n-cpu-moe 40` | interleave | | | | |
| Qwen3.6-27B (dense) | Q4_K_M | partial offload | pinned | | | | |
| gpt-oss-120b | MXFP4 | `--n-cpu-moe 35` | interleave | \* | \* | \* | \* |

\* After upgrade A1 only — doesn't fit in 64 GB.

### Multi-GPU rows — the 1660 Super experiment

The point of these is watching `--n-cpu-moe` fall to zero and tg128 jump as weight reads move off
DDR4. Add a row per card; stop when tg128 stops improving.

| GPUs | Total VRAM | `--n-cpu-moe` | `--tensor-split` | pp512 | tg128 | Notes |
|---|---|---|---|---|---|---|
| 2080 only | 8 GB | 40 | — | | | baseline |
| 2080 + 1× 1660S | 14 GB | ? | `8,6` | | | |
| 2080 + 2× 1660S | 20 GB | ? | `8,6,6` | | | |
| 2080 + 3× 1660S | 26 GB | **0?** | `8,6,6,6` | | | model should fit entirely |
| 2080 + 4× 1660S | 32 GB | 0 | `8,6,6,6,6` | | | KV headroom; check power/heat |

---

## What's settled and what isn't

### Answered

| Question | Answer |
|---|---|
| Does `llama-swap` serve `/v1/messages`? | **Yes** — docs list `v1/messages` and `v1/messages/count_tokens`. Still worth an end-to-end Claude Code test |
| Are the CPUs engineering samples? | **Yes** — `Genuine Intel(R) CPU 0000` is the canonical signature. Don't flash the BIOS |
| Will the Samsung RAM work? | **Yes** — row 1 of ASUS's QVL. The faults were individual modules/slots |
| Can the box hold 128 GB? | **No, not with these sticks.** Settled at 64 GB |
| How many PCIe slots? | Six physical x16: four at x16 electrical, two at x8 |
| Is a second RTX 2080 the best first GPU move? | **No** — the six 1660 Supers already on hand give more VRAM for nothing |

### Still open

- **Does the 1660 Super experiment work?** The single highest-value unknown. If pooled VRAM holds
  `coder` entirely, `--n-cpu-moe` goes to zero and generation escapes DDR4 — potentially ~5× on the
  number that matters. Free to test, so test it before buying anything.
- **How many cards physically fit,** given dual-slot coolers, the RAM-blocked top slot, and 8-pin
  connector count? Dry-fit before planning around a number.
- **What's the actual pp512 on `coder`?** More than tg128, this decides whether use case 1 is a
  tool or a demo — and it's the one thing tensor-core-less 1660s may not fix.
- **Which NUMA node owns the 2080's PCIe root**, and does pinning to it beat the other? With cards
  spread across both sockets this gets more interesting, not less.
- **Is the top slot blocked by the DIMM sockets or the installed modules?** Now that only 8 slots
  are populated, some may already be clear. Five minutes with the side panel off.
- **What is `Configured Memory Speed` reporting?** Should be 2133 at 1 DPC. Confirms the tok/s
  estimates in this document.
- **What bandwidth are you actually achieving?** `mbw` / Intel MLC, compared against theoretical
  for whatever `dmidecode` reports.
- **Did all sixteen DIMMs come from the same production lot?** Mixed RCD revisions under one part
  number are an uncommon but real source of instability. `dmidecode -t memory` lists each module.

## Sources
- [llama.cpp adds the Anthropic Messages API](https://huggingface.co/blog/ggml-org/anthropic-messages-api-in-llamacpp) · [Running gpt-oss with llama.cpp (Discussion #15396)](https://github.com/ggml-org/llama.cpp/discussions/15396) · [Multi-NUMA inference (Discussion #19102)](https://github.com/ggml-org/llama.cpp/discussions/19102) · [llama-server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [Performant local MoE CPU inference with GPU acceleration in llama.cpp](https://huggingface.co/blog/Doctor-Shotgun/llamacpp-moe-offload-guide) · [GPT-OSS 120B: offloading MoE layers to CPU](https://www.hardware-corner.net/gpt-oss-offloading-moe-layers/)
- [llama-swap](https://github.com/mostlygeek/llama-swap) — "Reliable model swapping for any local OpenAI/Anthropic compatible server"
- [Aider: OpenAI-compatible APIs](https://aider.chat/docs/llms/openai-compat.html)
- [Qwen3.6-35B-A3B GGUF (Unsloth)](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF) · [announcement](https://qwen.ai/blog?id=qwen3.6-35b-a3b)
- [Xeon E5-2630 v4 specs (Intel)](https://www.intel.com/content/www/us/en/products/sku/92981/intel-xeon-processor-e52630-v4-25m-cache-2-20-ghz/specifications.html) · [E5-2650 v4 (DDR4-2400)](https://www.intel.com/content/www/us/en/products/sku/91767/intel-xeon-processor-e52650-v4-30m-cache-2-20-ghz/specifications.html) · [E5-2600 v4 detailed specs (Microway)](https://www.microway.com/knowledge-center-articles/detailed-specifications-of-the-intel-xeon-e5-2600v4-broadwell-ep-processors-2/) · [DDR4 RDIMM validation, 2133 @ 2DPC (Intel PDF)](https://www.intel.com/content/dam/www/public/us/en/documents/platform-memory/ddr4-rdimm-xeon-e5-v4-validation-results.pdf)
- [Z10PE-D16 WS specs + memory footnotes (ASUS)](https://www.asus.com/me-en/motherboards-components/motherboards/workstation/z10ped16_ws/techspec/) · **[Official memory QVL / DIMM AVL, 2018-03-28 (PDF)](https://dlcdnets.asus.com/pub/ASUS/mb/Socket2011-R3/Z10PE-D16_WS/QVL/Z10PE-D16_WS_TS700-E8_TS700-E8_V2_DIMM_AVL_20180328.pdf)** — M393A1G40DB0-CPB is row 1 · [PCIe slots with one CPU (ASUS FAQ)](https://www.asus.com/us/support/faq/1016607/) · [Z10PE-D16 series manual (PDF)](https://dlcdnets.asus.com/pub/ASUS/mb/Socket2011-R3/Z10PE-D16/Manual/E13695_Z10PE-D16_Series_UM_V4_WEB.pdf)
- Anecdotal: [Why won't Z10PE-D16 WS support 128GB (Tom's Hardware)](https://forums.tomshardware.com/threads/why-wont-z10pe-d16-ws-support-128gb-ddr4-2400-mhz-ecc.2739002/) — the 2DPC/1866 reports · [Asus Z10PE-D16 WS Owners Thread (Overclock.net)](https://www.overclock.net/threads/asus-z10pe-d16-ws-owners-thread.1579548/) — population order, B7/B1 POST codes, per-slot faults · [Z10PE-D16 WS will not post](https://forums.tomshardware.com/threads/z10pe-d16-ws-will-not-post.2877611/) · [error code b7 (Linus Tech Tips)](https://linustechtips.com/topic/1189902-asus-z10pe-d16-ws-error-code-b7/)
- Q-Code: **[Z10PE-D16 series manual, Q-Code table p.42 (ManualsLib)](https://www.manualslib.com/manual/890924/Asus-Z10pe-D16-Series.html?page=42)** — B0–BC = MRC Progress / Memory Init.; 5A = Memory Init. Done. Note this **overrides** the generic [AMI Aptio 5.x status codes](https://www.congatec.com/fileadmin/user_upload/Documents/Others/AMI_Aptio_5.x_Status_Codes_PUB_Rev.2.0_20140410.pdf), where 0xB0 means "Set Virtual Address Map Begin"
- **Per-code MRC table (the useful one):** [Intel S2600CW TPS, Table 94 MRC Progress Codes](https://www.manualslib.com/manual/1326799/Intel-S2600cw.html?page=196) and [Intel S2600CO TPS, Tables 78/79](https://www.manualslib.com/manual/563433/Intel-S2600co-Family.html?page=156) — both Grantley (E5-2600 v3/v4), same MRC as this board. B0 = Detect DIMM population; B7 = Train DDR4 ranks; BF = MRC done; E8 = no usable memory · [Fixing bent pins LGA2011 (Overclock.net)](https://www.overclock.net/threads/fixing-bent-pins-lga2011.1544011/)
- Clear CMOS: **[Z10PE-D16 series manual, Jumpers p.44 (ManualsLib)](https://www.manualslib.com/manual/890924/Asus-Z10pe-D16-Series.html?page=44)** — CLRTC1 is the CMOS clear; cap must return to pins 1–2 or the system won't boot · [How to Clear CMOS (ASUS)](https://zentalk.asus.com/t5/faq/how-to-clear-cmos/ta-p/407728) · [+5VSB keeps CMOS alive with AC connected; jumper-with-standby can burn a diode](https://hardforum.com/threads/reset-cmos-without-disconnecting-power-supply-fried-motherboard.1414060/)
- Memory population: **[Z10PE-D16 series manual, System Memory p.32–33 (ManualsLib)](https://www.manualslib.com/manual/890924/Asus-Z10pe-D16-Series.html?page=32)** — *"When installing only one DIMM in a single CPU configuration, install the DIMM on either A1 or B1"*; dual-CPU population table starts at 2 DIMMs · **[Memory Error LEDs ERR_DIMMA1–ERR_DIMMH1 + BMC_LED1](https://mans.io/files/viewer/565194/40)** · [Each CPU needs its own memory to POST](https://forums.tomshardware.com/threads/memory-upgrade-for-dual-socket-xeon-workstation.3730808/)
- Balanced population: [Fujitsu — Memory Performance of Xeon E5-2600 v4 (Broadwell-EP)](https://sp.ts.fujitsu.com/dmsp/Publications/public/wp-broadwell-ep-memory-performance-ww-en.pdf) — interleave sets require equal channel capacity; unbalanced configs split into multiple sets with inconsistent bandwidth · [How to properly populate memory on dual-socket Intel server boards](https://www.intel.com/content/www/us/en/support/articles/000025039/server-products/server-boards.html) — fill-farthest / blue-slot-first rule
- [Identifying an Intel Engineering Sample (Intel)](https://www.intel.com/content/www/us/en/support/articles/000056190/processors.html) · [Signs an Intel CPU may be an ES](https://chris.partridge.tech/2021/identifying-intel-engineering-samples/) · [Samsung M393A1G40DB0-CPB = DDR4-2133](https://semiconductor.samsung.com/dram/module/rdimm/m393a1g40db0-cpb/)
- [NVIDIA v580 ends Maxwell/Pascal/Volta; Turing retained (TechPowerUp)](https://www.techpowerup.com/338497/nvidias-v580-driver-branch-ends-support-for-maxwell-pascal-and-volta-gpus) · [llama.cpp multi-GPU docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/multi-gpu.md) · [Best used GPU for local LLM 2026](https://bestgpuforllm.com/articles/best-used-gpu-for-llm/)
- [Single-device data redundancy with btrfs](https://zejn.net/b/2017/04/30/single-device-data-redundancy-with-btrfs/) · [Bad sectors: ZFS vs legacy RAID](https://forums.anandtech.com/threads/bad-sectors-zfs-versus-legacy-raid.2424260/post-37246481) · [Interpreting SMART attributes](https://bbs.archlinux.org/viewtopic.php?id=272782)
- [Open WebUI + llama.cpp](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-llama-cpp/) · [vLLM GPU support matrix](https://docs.vllm.ai/en/stable/getting_started/installation/gpu/)
- Context signalling: **[Claude Code env vars — `CLAUDE_CODE_AUTO_COMPACT_WINDOW`](https://code.claude.com/docs/en/env-vars)** · [Gateway protocol — model discovery](https://code.claude.com/docs/en/llm-gateway-protocol#model-discovery) (reads only `id`/`display_name`; filters non-`claude`/`anthropic` IDs) · [Model configuration](https://code.claude.com/docs/en/model-config) · [Custom model context window >200k (issue #68522, open)](https://github.com/anthropics/claude-code/issues/68522)
- Overnight work: [llama.cpp perplexity tool](https://github.com/ggml-org/llama.cpp/blob/master/tools/perplexity/README.md) · [faster-whisper](https://pypi.org/project/faster-whisper/) — CTranslate2 CUDA backend outperforms whisper.cpp on NVIDIA
- [Canonical releases Ubuntu 26.04 LTS](https://canonical.com/blog/canonical-releases-ubuntu-26-04-lts-resolute-raccoon) · [26.04 ships native CUDA (Neowin)](https://www.neowin.net/news/ubuntu-2604-lts-resolute-raccoon-is-now-available-with-linux-70-and-native-cuda/) · [26.04 release notes](https://documentation.ubuntu.com/release-notes/26.04/) · [Ubuntu release cycle](https://ubuntu.com/about/release-cycle) · [Installing NVIDIA drivers on 26.04](https://linuxconfig.org/how-to-install-nvidia-drivers-on-ubuntu-26-04)
- [DKMS vs kmod for ZFS (Klara Systems)](https://klarasystems.com/articles/dkms-vs-kmod-the-essential-guide-for-zfs-on-linux/) · [ZFS on Debian: DKMS and contrib](https://www.bigiron.cc/guides/zfs-on-debian-installation-and-dkms) · [zfs-dkms in Debian trixie](https://packages.debian.org/trixie/zfs-dkms)
