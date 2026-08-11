# Homelab AI host — as code

`HOST_SETUP.md` turned into something you can run twice.

The runbook stays the source of truth for *why*; this directory is the *how*, with the
manual steps made idempotent, the interactive ones made declarative, and the
"record this number somewhere durable" ones made into files that land in git.

Phase numbers and tags match the runbook 1:1.

## Layout

```
ansible.cfg              # fact cache lives here — Phase 3 discovers the GPU's
                         #   NUMA node, Phase 7 pins to it
site.yml                 # the build, in phase order
verify.yml               # post-install checks + the monthly maintenance pass
requirements.yml         # collections
Makefile                 # make help
inventory/
  hosts.yml              # the box
  group_vars/aihost.yml  # every tunable in the runbook, in one place
  host_vars/clode.yml    # disk by-id paths — the only values you MUST fill in
roles/
  base/                  # Phase 1  packages, unattended-upgrades
  hardware/              # Phase 2  asserts + records baselines
  gpu/                   # Phase 3  driver, CUDA, NUMA discovery
  storage/               # Phase 4  zpool, datasets, scrub, caches
  llama_cpp/             # Phase 5  CUDA + TLS build
  models/                # Phase 6  cache pre-warm
  llama_swap/            # Phase 7  the front door, both API dialects
  docker_webui/          # Phase 8  Docker + Open WebUI
  clients/               # Phase 10 Claude Code wrapper, Aider settings
  firewall/              # Phase 11 ufw, LAN-only
tests/                   # offline tests: output parsing + template rendering
artifacts/               # baselines and client configs fetched off the host
```

**Phase 9 (Lemonade) is deliberately not implemented.** `LOCAL_AI_PLAN.md` lists
it as the "Demo layer — the 'look how easy this is' segment. **Keep it, don't
build on it**", and describes it as a manager wrapped around llama.cpp rather
than a different engine. None of the three real use cases depend on it, and its
`llamacpp_args` blocks `-ngl`, which is the exact MoE-offload knob this box is
built around. Install it by hand for the camera. Its port (13305) is
correspondingly *not* opened by Phase 11.

Slow or destructive checks live behind their own tags:

```bash
make apply TAGS=dialects   # loads a model and probes both API dialects
make bench EXTRA='-e llama_cpp_bench_model=<path> -e llama_cpp_bench_extra="--n-cpu-moe 40"'
```

## First run

```bash
make deps                       # collections
make test                       # offline parsing tests, no host required
make syntax                     # playbooks parse

# Fill in the disk by-id paths first — the storage role refuses to guess.
$EDITOR inventory/host_vars/clode.yml

make check                      # full dry run against the box
make apply TAGS=phase1          # one phase at a time
```

Nothing destructive runs without an explicit flag:

```bash
make apply TAGS=storage EXTRA='-e aihost_allow_zpool_create=true'
make apply TAGS=storage EXTRA='-e aihost_allow_disk_format=true'
make apply TAGS=phase3  EXTRA='-e aihost_allow_reboot=true'
```

## What changed from the runbook, and why

These are deliberate departures. Everything else is a transcription.

| Runbook | Here | Why |
|---|---|---|
| `dpkg-reconfigure -plow unattended-upgrades` | Templated `52homelab-unattended-upgrades` | The dialog is interactive, so it is not repeatable. The template also `#clear`s the origins list, which appending alone would not do. |
| `sudo chown $USER /opt` | Only `/opt/llama.cpp` is user-owned | The build needs one directory, not all of `/opt`. |
| `smartctl -a ... \| grep -E '^  (5\|187\|...)'` | `smartctl -j` + JSON parse | The grep depends on smartctl's column padding. The raw JSON is kept as the durable baseline. |
| `mbw ... \| tail -3` read by eye | Parsed, asserted, written to a dated baseline file and fetched into `artifacts/` | "Record this number somewhere durable" should not mean a terminal scrollback. |
| `mkfs.ext4 /dev/sdX` | `community.general.filesystem` behind a blank-disk guard | See `roles/storage/tasks/assert_blank.yml`. |
| Phase 3 note "**Note the result**" | Persisted to `/etc/ansible/facts.d/aihost.fact` | So `--tags phase7` alone still knows where to pin. |
| — | `llama-server` is checked for linked CUDA | A CUDA-less build silently falls back to CPU and invalidates every tok/s number in `LOCAL_AI_PLAN.md`. |

## Tests

`make test` runs `tests/parsing.yml` on the control node against recorded fixtures
in `tests/fixtures/`. It covers the expressions that parse `dmidecode`, `numactl`,
`smartctl -j` and `mbw` output — the places where a wrong regex fails silently and
produces a confident, wrong assertion.

It has already earned its keep: it caught that `\\D` inside a YAML folded scalar is
a literal double-backslash and never matched (so every DIMM speed parsed as `0`),
and that the runbook's `mbw` parse looks for a `MiB/s:` token that `mbw` does not
print — the value comes after `Copy:`, before the unit.

## Measured on the box

Recorded 2026-08-02, llama.cpp `11924d4`, `Qwen3.6-35B-A3B-UD-Q4_K_M` (20.6 GiB),
`-ngl 999 --n-cpu-moe 40`:

| test | t/s |
|---|---|
| pp512 | 214.54 ± 1.72 |
| tg128 | 20.16 ± 0.09 |

Through llama-swap over the API, with a short context, the same model serves at
~25 tok/s. Both are **above** `LOCAL_AI_PLAN.md`'s 10–18 tok/s estimate.

NUMA pinning is confirmed working, not just configured: `bind:0` mempolicy on 313
mappings, and `numastat` reports 19,989 MB on node 0 against 31 MB on node 1.
(`Mems_allowed_list` shows `0-1` even when membind is active — it reflects cpuset
cgroups, not memory policy. Don't read it as a failure.)

## Bugs this caught by being run for real

Phases 1–5 have been applied to `clode` and re-run to `changed=0`. Four things
only showed up on contact with the actual box:

- **`aihost_user` resolved to `root`.** It defaulted to `ansible_user_id`, which
  under `become: true` is the post-escalation user. `/srv/models` came out
  root-owned and llama-swap's `User=` would have followed, with nothing failing.
  Now uses the login user, guarded by a `pre_task` assert that refuses `root`.
- **`regex_search` backreferences do not survive `assert`'s conditional
  templating** — the VRAM check died with "Unknown argument" although the same
  filter works standalone. Replaced with `--format=csv,noheader,nounits` + `split`.
- **A pinned SHA is incompatible with `depth: 1`.** Shallow-fetching an arbitrary
  object needs server cooperation; it works on an already-cloned host and fails
  on a fresh one. `depth` is now conditional on tracking a branch.
- **`INJECT_FACTS_AS_VARS`** is deprecated (removed in ansible-core 2.24). All
  bare `ansible_*` facts are now `ansible_facts.*`. A live run emits zero
  deprecation warnings.
- **llama.cpp built without TLS.** `libssl-dev` was missing, so CMake silently
  produced a no-HTTPS binary. It started, reported its version, listed `CUDA0`,
  linked CUDA — and could not fetch a single model, which is how every model in
  Phases 6 and 7 arrives. Now `libssl-dev` is a Phase 1 package,
  `LLAMA_OPENSSL: "ON"` is explicit, and there is an assert beside the CUDA one.
- **The cache-detection glob could never match.** llama.cpp uses the HuggingFace
  hub layout — content-addressed `blobs/<sha256>` with real names existing only
  as symlinks under `snapshots/<commit>/`. The default `file_type: file` misses
  symlinks and a `size:` filter measures the link, not the target, so every run
  would have re-downloaded all 38 GB.
- **The fact cache froze `ansible_facts.date_time`.** With `fact_caching_timeout`
  at 24h, recorded baselines and their dated filenames carried a stale
  timestamp — which quietly breaks the "diff it against last month" workflow the
  baselines exist for. Runs are now stamped from a fresh `date` at play start.
- **`--tags bench` was referenced in three places but never defined**, and
  `include_tasks` needs `apply:` for tags to reach the included tasks (the
  dialect probe silently ran zero tasks and reported success).
- **The hardware role could never report `changed=0`**, because it rewrote a
  timestamped report every converge. Now one baseline per day
  (`-e hardware_force_baseline=true` to override), so `changed` means something.

## Gotchas worth knowing

- **Both Qwen models are reasoning models.** They emit a thinking block before
  any user-visible text, and it consumes the token budget. A 32-token probe
  returns an empty `content` with `finish_reason: length` and looks exactly like
  a broken endpoint. On `/v1/messages` this surfaces as separate `thinking` and
  `text` blocks — which is what Claude Code wants — but budget for it, and
  expect it to interact with the scorer's `--temp 0 --seed 42` structured output.
- **`-e key=value` splits on whitespace.** `-e 'x=--n-cpu-moe 40'` silently drops
  the `40`. Use JSON for multi-word values.
- **`copies=2` exactly doubles on-disk cost**: 38.9 G logical → 77.8 G used.
- **llama.cpp auto-fetches `mmproj` for multimodal repos**, so the footprint
  exceeds the sum of the quant sizes even for text-only use.

## Where the plan and the hardware disagree

Recorded because `LOCAL_AI_PLAN.md` predates the build:

- **CUDA is 12.4, not 13.3.** The plan's case for 26.04 cites CUDA 13.3 in the
  archive. `nvidia-cuda-toolkit` is 12.4. It builds fine for sm_75 with GCC 15.2.
- **NUMA node 1 has 30148 MB, not 32 GB** (node 0 has 31810 MB). Size anything
  socket-pinned against ~29 GB.
- **No spare 1 TB disk is fitted.** `/srv/evaldata` is unprovisioned and
  `aihost_evaldata_disk_by_id` is empty; the storage role skips it and says so.
- **The 8 TB is worse than "has SMART errors".** 31,360 reallocated sectors
  (normalized 92 vs threshold 10) and `Reported_Uncorrect` at **normalized 1
  against a threshold of 0** — one point from failing SMART. Pending and offline
  uncorrectable are both 0, and `copies=2` is exactly the mitigation for this.

## Security notes

- **Docker bypasses ufw.** Published container ports are handled by Docker's own
  iptables rules in the `DOCKER-USER` chain, evaluated *before* ufw — so the
  Phase 11 rules do **not** filter port 3000. Open WebUI is published bound to
  the LAN IP rather than `0.0.0.0` to limit the blast radius, but if this box
  ever gains a public interface, add an explicit `DOCKER-USER` rule. The
  runbook's "ufw allow 3000" implies a protection that does not exist.
- **The Phase 11 role refuses to lock you out.** It reads every established SSH
  peer from the kernel and asserts each is inside `aihost_lan_subnet` before
  enabling a default-deny firewall, and arms a `systemd-run` dead-man's switch
  that disables ufw after 5 minutes unless connectivity is re-confirmed.
- **`local-claude` unsets `ANTHROPIC_API_KEY`** rather than setting it empty. A
  non-empty value takes precedence and silently bills the real Anthropic API.
  It is a wrapper, not shell exports, so plain `claude` is unaffected.

## Known gaps

- **No spare disk is fitted.** `/srv/evaldata` does not exist. Open WebUI's
  volume — chat history, RAG documents, accounts, the only non-re-downloadable
  data here — sits on the boot SSD under `/var/lib/docker` with **no backup**.
  That is the one real hole in this build.
- The 8 TB holds ~78 G of models and its `Reported_Uncorrect` is one normalized
  point above the SMART failure threshold. All of it is re-downloadable by
  design, which is the plan working — but it is 78 G you would be re-pulling.

## Still to build

Nothing from the runbook, other than Lemonade (skipped on purpose, above).
Phases 1–11 are applied to `clode` and the whole playbook converges at
`changed=0`; `verify.yml` asserts all of it.
