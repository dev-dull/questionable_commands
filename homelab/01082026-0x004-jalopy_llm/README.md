## Questionable Commands - Homelab - Ep. 0x004 - Local AI

Turning a 2016 dual-Xeon server and a 2018 gaming card into a local AI host that Claude Code,
Aider, and a batch eval harness all talk to. Along the way: a motherboard that wouldn't POST, a
POST code the manual refuses to explain, and giving up on half the RAM.

<!-- [![Questionable Commands - Ep. 0x004 - Local AI](https://img.youtube.com/vi/VIDEO_ID/maxresdefault.jpg)](https://www.youtube.com/watch?v=VIDEO_ID) -->

### The hardware

| | |
|---|---|
| Board | Asus Z10PE-D16 WS |
| CPU | 2× Xeon E5-2630 v4 — **engineering samples**, they report as `Genuine Intel(R) CPU 0000` |
| RAM | 64 GB DDR4-2133 ECC (8× 8 GB, 1 DIMM per channel — *after* the 128 GB attempt failed) |
| GPU | RTX 2080 8 GB |
| Storage | 120 GB Kingston SSD boot · 8 TB Seagate flagged for SMART errors (31,360 reallocated sectors, 0 pending), running ZFS `copies=2`. Two disks by design — anything not re-downloadable lives off-box |

### What's in here

| File | What it is |
|---|---|
| [`LOCAL_AI_PLAN.md`](LOCAL_AI_PLAN.md) | The research and planning doc. Hardware analysis, model selection, why the memory bandwidth number matters more than the core count, upgrade paths, and the open questions. |
| [`HOST_SETUP.md`](HOST_SETUP.md) | The build runbook — ten phases of commands with verification checkpoints. |
| [`ansible/`](ansible/) | The same runbook made idempotent. Phase numbers and tags map 1:1. |
| `claude-local.sh` | Wrapper that points Claude Code at the box instead of Anthropic's API. |

### The short version

`llama-server` speaks Anthropic's Messages API natively at `/v1/messages`, so Claude Code points
at a local box with four environment variables and no translation proxy. [`llama-swap`](https://github.com/mostlygeek/llama-swap)
sits in front serving both the OpenAI and Anthropic dialects, starting the right model on demand.

```bash
export ANTHROPIC_BASE_URL=http://<host>:8080
export ANTHROPIC_AUTH_TOKEN=local
unset  ANTHROPIC_API_KEY          # a set key silently wins and bills the real API
export ANTHROPIC_MODEL=coder
claude
```

The trick that fits a 35-billion-parameter model on an 8 GB card:

```bash
-ngl 999 --n-cpu-moe 40
```

Send every layer to the GPU, then send the mixture-of-experts weights back to system RAM. Attention
and KV cache stay on the card where latency matters; the huge, sparsely-touched expert weights live
in cheap DDR4. Neither component could do it alone.

The same trick reportedly runs `gpt-oss-120b` on 8 GB of VRAM — but that needs 61 GB of system RAM
for the experts, and this box only has 64 GB with an OS in the way. See *How it ended*.

### Two things that cost a whole evening

**`B0` does not mean what the internet says.** Generic AMI Aptio tables call `0xB0` *"Set Virtual
Address Map Begin"* — a late boot stage that would send you chasing boot devices. On this board
it's memory. Intel's Technical Product Specs for the same Grantley silicon publish the real table,
where ASUS's manual just says "Memory Init." for fourteen consecutive codes:

| Code | Actually means |
|---|---|
| `B0` | Detect DIMM population |
| `B7` | Train DDR4 ranks |
| `BF` | MRC done |
| `E8` | Fatal — no usable memory |

Watching the code move `B0` → `B7` → `B0` across a week of swapping sticks is watching the failure
change character. Full decoder table and the diagnostic path are in
[`LOCAL_AI_PLAN.md`](LOCAL_AI_PLAN.md).

**The board has eight DIMM error LEDs** — `ERR_DIMMA1` through `ERR_DIMMH1`, sitting right next to
the slots, lighting up to tell you exactly which module it doesn't like. Nobody reads that page of
the manual.

### How it ended

16 sticks never POSTed. 8 did. The build settled at 64 GB, which puts `gpt-oss-120b` out of reach
until a memory upgrade. Everything the box is actually *for* — Claude Code, Aider, and the batch
eval harness — still works at 64 GB.
