# Homelab AI Host — Setup Runbook

Build instructions for the dual-Xeon inference host. Rationale, benchmarks, and upgrade planning
live in `LOCAL_AI_PLAN.md`; this file is commands only.

**Target hardware:** Asus Z10PE-D16 WS · 2× Xeon E5-2630 v4 (engineering samples) · 64 GB DDR4-2133
(8× 8 GB, 1 DIMM per channel) · RTX 2080 8 GB (NUMA node 0) · 120 GB SSD (boot) · 8 TB HDD (models)

**As built:** `clode.deep13.lol` · Ubuntu 26.04 LTS, kernel 7.0.0-28 · NUMA node 0 = 31810 MB,
node 1 = 30148 MB (asymmetric — size pinned models against the smaller). Two disks by design:
anything not re-downloadable is kept off-box.

---

## ⚠️ Read before touching the machine

- **Do not flash the BIOS.** The CPUs are engineering samples; a firmware update can drop the
  microcode they need and leave the board unable to POST.
- **Memory is 8 sticks at 1 DIMM per channel** (`A1 B1 C1 D1` + `E1 F1 G1 H1`). Do not add more
  without re-reading the troubleshooting log — 12 is unbalanced, 16 has known faults on this board.
- **The 8 TB drive has SMART errors.** Only re-downloadable data goes on it.
- **This is a LAN-only service.** Nothing here is safe to expose to the internet.

---

## Phase 1 — Base system

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y build-essential cmake git curl jq numactl htop nvtop \
                    smartmontools zfsutils-linux pciutils mbw
```

`mbw` lives in **universe**; if apt can't find it, `sudo add-apt-repository universe` first.
`jq` is needed by the checkpoints later in this file.

### Security-only unattended upgrades, never unattended kernel reboots

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

Ensure `/etc/apt/apt.conf.d/50unattended-upgrades` has:

```
Unattended-Upgrade::Automatic-Reboot "false";
```

A kernel bump that breaks the ZFS module must not happen while you're asleep.

---

## Phase 2 — Verify hardware

```bash
# Both CPUs, both NUMA nodes. Note the nodes are asymmetric: ~31.8 GB and ~30.1 GB
numactl --hardware

# Memory should report 2133 MT/s under "Configured Memory Speed"
sudo dmidecode -t memory | grep -E 'Locator|Size|Configured Memory Speed'

# Achieved bandwidth baseline — record this number
mbw -q -n 10 1024 | tail -3

# Identify the disks BEFORE running anything destructive
lsblk -o NAME,SIZE,MODEL,SERIAL,MOUNTPOINT
```

Then, using the correct device node for the 8 TB from `lsblk`:

```bash
sudo smartctl -a /dev/sdX | grep -E '^  (5|187|188|197|198) '
sudo smartctl -t long /dev/sdX          # ~12h; check back with -a
```

Record the SMART raw values somewhere durable; re-check monthly. Trend matters more than the
absolute numbers.

---

## Phase 3 — GPU driver and CUDA

```bash
sudo ubuntu-drivers install
sudo reboot
```

`ubuntu-drivers install` is the correct verb on 26.04 — `autoinstall` is no longer listed.

After reboot:

```bash
nvidia-smi              # RTX 2080, 8192 MiB
nvcc --version          # CUDA toolkit from the archive (native on 26.04)
```

### Find which NUMA node owns the GPU — needed in Phase 7

```bash
GPU_BDF=$(lspci -D | grep -i 'VGA.*NVIDIA' | cut -d' ' -f1)
cat /sys/bus/pci/devices/$GPU_BDF/numa_node
```

Note the result (`0` or `1`). Everything gets pinned to that node.

---

## Phase 4 — Storage

### Model pool on the 8 TB (copies=2 so scrubs can self-heal bad sectors)

```bash
ls -l /dev/disk/by-id/          # find the stable id for the 8 TB

sudo zpool create -o ashift=12 -O compression=off tank /dev/disk/by-id/ata-XXXXXXXX
sudo zfs create -o copies=2 -o recordsize=1M -o mountpoint=/srv/models tank/models
sudo chown -R $USER:$USER /srv/models
```

Always use the `by-id` path, never `/dev/sdX` — kernel device names are not stable across reboots.

### Verify ZFS is the prebuilt module, not DKMS

```bash
modinfo zfs | grep -E 'filename|version'
# filename should be under /lib/modules/.../kernel/ — not a dkms path
```

### Monthly scrub + notifications

```bash
sudo systemctl enable --now zfs-scrub-monthly@tank.timer
sudoedit /etc/zfs/zed.d/zed.rc      # set ZED_EMAIL_ADDR / notification hook
sudo systemctl enable --now zfs-zed
```

### Optional: a third disk for results

This build runs on two disks and keeps eval sets, scoring results, and benchmark CSVs **off-box** —
the 8 TB is a failing drive that should only hold things you can re-download, and the boot SSD
isn't somewhere to put research output either.

If you'd rather keep results local, fit a third drive and do this (then set
`aihost_evaldata_disk_by_id` if you're using the Ansible path):

```bash
sudo mkfs.ext4 -L evaldata /dev/sdX          # confirm device with lsblk first
sudo mkdir -p /srv/evaldata
echo 'LABEL=evaldata /srv/evaldata ext4 defaults 0 2' | sudo tee -a /etc/fstab
sudo mount -a
sudo chown -R $USER:$USER /srv/evaldata
```

### Point the model cache at the pool

```bash
sudo tee /etc/profile.d/aihost.sh >/dev/null <<'EOF'
export LLAMA_CACHE=/srv/models/llama
export HF_HOME=/srv/models/hf
EOF
source /etc/profile.d/aihost.sh
mkdir -p "$LLAMA_CACHE" "$HF_HOME"
```

`LLAMA_CACHE` is what llama.cpp's own `-hf` downloader uses. `HF_HOME` is for the `hf` CLI — they
are **separate caches**, which is why Phase 6 pre-warms via llama.cpp rather than `hf download`.

**After every kernel update:** run `zpool status` before walking away. Keep a known-good kernel in
the GRUB menu.

---

## Phase 5 — Build llama.cpp with CUDA

```bash
sudo mkdir -p /opt && sudo chown $USER /opt
git clone https://github.com/ggml-org/llama.cpp /opt/llama.cpp
cd /opt/llama.cpp

# Pin to the revision built and verified on clode: CUDA linked, CUDA0 detected,
# GCC 15.2.0 host compiler against CUDA 12.4. Tracking master means the next
# build may not reproduce this one.
git checkout 11924d4c17abc27383376a1ac6a24fa3e36c1c0c

cmake -B build \
  -DGGML_CUDA=ON \
  -DCMAKE_CUDA_ARCHITECTURES=75 \
  -DGGML_NATIVE=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j 20
```

`CMAKE_CUDA_ARCHITECTURES=75` targets Turing only and cuts build time substantially.

### Checkpoint

```bash
/opt/llama.cpp/build/bin/llama-server --version
/opt/llama.cpp/build/bin/llama-bench -m <any-small-gguf> -ngl 999
```

Record `pp512` and `tg128`. These are your baselines.

---

## Phase 6 — Pre-warm the model cache

64 GB of RAM sets the ceiling. Budget ~50 GB max per model; **~28 GB** for anything you want
pinned to a single NUMA node — size against the smaller node (30.1 GB), not a flat 32.

Let llama.cpp do the downloading so the files land in `LLAMA_CACHE` where `-hf` will find them.
Run each of these once and Ctrl-C after the model finishes loading:

```bash
cd /opt/llama.cpp/build/bin

./llama-server -hf unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M --port 8099   # 20 GB, coder
./llama-server -hf unsloth/Qwen3.5-9B-GGUF:Q4_K_M         --port 8099   # 5.2 GB, scorer
./llama-server -hf ggml-org/gpt-oss-20b-GGUF:MXFP4        --port 8099   # 12 GB, small
```

⚠️ **Always pin the quant.** `-hf <user>/<repo>[:quant]` defaults to `Q4_K_M` **but falls back to
the first file in the repo when that doesn't exist** — it does not fail. Verified against the real
repos:

- **Qwen3.6-35B-A3B ships no plain `Q4_K_M`** — only Unsloth-Dynamic `UD-*` variants. A bare `-hf`
  here silently serves whatever sorts first, which could be an IQ1_M or a BF16 shard.
- **gpt-oss-20b's repo also contains `eagle3-*`** speculative-decoding draft models a default
  picker could select. MXFP4 is the only real quant and must never be re-quantized.

Remember `tank/models` is `copies=2`, so each of these consumes twice its size on the pool.

**gpt-oss-120b (61 GB) will not fit in 64 GB.** Skip until the memory upgrade.

> Qwen3.5-9B is a multimodal (image-text-to-text) model. Text-only use needs nothing extra; if you
> later want vision, you'll need the matching `mmproj` file and `--mmproj`.

---

## Phase 7 — llama-swap (the front door)

One endpoint serving both the OpenAI and Anthropic dialects, swapping models on demand.
llama-swap supports `/v1/messages` and `/v1/messages/count_tokens`, which is what Claude Code uses.

```bash
LSVER=$(curl -s https://api.github.com/repos/mostlygeek/llama-swap/releases/latest | jq -r .tag_name)
curl -L "https://github.com/mostlygeek/llama-swap/releases/download/${LSVER}/llama-swap_${LSVER#v}_linux_amd64.tar.gz" \
  | sudo tar -xz -C /usr/local/bin llama-swap
sudo chmod +x /usr/local/bin/llama-swap
llama-swap --version
sudo mkdir -p /etc/llama-swap
```

Asset naming is `llama-swap_<version-without-v>_linux_amd64.tar.gz` (e.g. tag `v245` →
`llama-swap_245_linux_amd64.tar.gz`), which is what `${LSVER#v}` produces.

### `/etc/llama-swap/config.yaml`

The GPU's NUMA node on this box measured **0** (Phase 3) — that's what `coder` pins to below.
Tune `--n-cpu-moe` downward until it OOMs, then back off by 2.

⚠️ **`-c` is the *total* KV allocation and `-np` divides it between slots.** `-c 65536 -np 2` gives
each request only 32768 tokens, and Claude Code — which resends a large system prompt plus every
tool definition every turn — blows straight through it with
`request (32912 tokens) exceeds the available context size`. Measured on the box: 4922 / 8192 MiB
VRAM at `-c 131072`.

⚠️ **`coder` runs `-np 1`, deliberately.** Same `-c`, same VRAM — the single slot gets the whole
131072 instead of half. `-np 2` was tried and is unworkable for Claude Code: at 65536 per slot the
hard server ceiling and the compaction budget become the same number, so auto-compact fires with
no room left to run in, and `/compact` then fails too, because **compaction is itself a request
that must fit inside the window it is trying to free**:

```
API Error: 400 request (65873 tokens) exceeds the available context size (65536 tokens)
Error during compaction: 400 request (66585 tokens) exceeds the available context size (65536)
```

There is no safety net — Claude Code's *reactive* compaction matches "prompt too long" against
Anthropic's error phrasing, and llama.cpp's wording isn't in that set, so the overflow is never
recognised. The cost of `-np 1` is that two concurrent `coder` requests serialise. For two
occasional users that's a far better trade than a model that deadlocks.

**Set the client-side window below the ceiling, not equal to it** — see Phase 9.

```yaml
# A 20 GB MoE loading off a 5400rpm disk takes far longer than llama-swap's
# default health-check window, which kills it mid-load and reports a start
# failure. Without this the first `coder` request looks like a broken install.
healthCheckTimeout: 900

models:
  coder:
    cmd: >
      numactl --cpunodebind=0 --membind=0
      /opt/llama.cpp/build/bin/llama-server --port ${PORT} --host 127.0.0.1
      -hf unsloth/Qwen3.6-35B-A3B-GGUF:UD-Q4_K_M
      -ngl 999 --n-cpu-moe 40 --load-mode none -fa on
      -c 131072 -ctk q8_0 -ctv q8_0
      -t 10 -np 1 -b 4096 -ub 4096
    ttl: 3600

  scorer:
    cmd: >
      /opt/llama.cpp/build/bin/llama-server --port ${PORT} --host 127.0.0.1
      -hf unsloth/Qwen3.5-9B-GGUF:Q4_K_M
      -ngl 999 -fa on -c 16384 -np 8 --seed 42 --temp 0
    ttl: 600

  small:
    cmd: >
      /opt/llama.cpp/build/bin/llama-server --port ${PORT} --host 127.0.0.1
      -hf ggml-org/gpt-oss-20b-GGUF:MXFP4
      -ngl 999 --n-cpu-moe 22 -fa on
      -c 32768 -b 2048 -ub 2048 --temp 1.0 --top-p 1.0
    ttl: 600
```

Flag notes, all verified against current llama.cpp:

- **`-fa on`** — `--flash-attn` now takes `on|off|auto` (default `auto`). Bare `--flash-attn` is
  no longer the right form.
- **`--load-mode none`** — replaces the now-deprecated `--no-mmap`. Modes are
  `none|mmap|mlock|mmap+mlock|dio`; `none` loads into RAM without memory-mapping.
- **`-ctk` / `-ctv`** — short forms of `--cache-type-k` / `--cache-type-v`.
- **`--jinja` is enabled by default** now, so it's omitted.
- gpt-oss wants `--temp 1.0 --top-p 1.0` and no repetition penalty.

### `/etc/systemd/system/llama-swap.service`

```ini
[Unit]
Description=llama-swap — model-swapping front door for llama.cpp
Documentation=https://github.com/mostlygeek/llama-swap
# The models live on tank/models. Starting before the pool mounts gives you a
# service that is up but cannot load a single model.
After=network-online.target zfs-mount.service
Wants=network-online.target

[Service]
Type=simple
User=<user>
Group=<user>
ExecStart=/usr/local/bin/llama-swap --config /etc/llama-swap/config.yaml --listen 0.0.0.0:8080
Restart=on-failure
RestartSec=5

# Both caches. llama-swap execs llama-server, which resolves -hf against
# LLAMA_CACHE; without this the service re-downloads into the user's home.
Environment=LLAMA_CACHE=/srv/models/llama
Environment=HF_HOME=/srv/models/hf

# A model load is a long, memory-hungry operation. Don't let systemd's default
# OOM handling take the whole service down with one llama-server.
OOMPolicy=continue

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now llama-swap
journalctl -u llama-swap -f
```

### Checkpoint — both dialects must answer

```bash
# OpenAI dialect
curl -s http://localhost:8080/v1/models | jq .

# Anthropic dialect (this is what Claude Code uses)
curl -s http://localhost:8080/v1/messages \
  -H 'content-type: application/json' \
  -d '{"model":"coder","max_tokens":64,"messages":[{"role":"user","content":"Say OK."}]}' | jq .
```

First call to a model will be slow — it has to start `llama-server` and load weights.

---

## Phase 8 — Docker + Open WebUI

Use Docker's own repo — **not** the snap, whose confinement breaks bind mounts and GPU access.

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker

docker run -d --restart unless-stopped \
  -p 3000:8080 \
  -v open-webui:/app/backend/data \
  -e OPENAI_API_BASE_URL=http://<host-lan-ip>:8080/v1 \
  -e OPENAI_API_KEY=local \
  --name open-webui ghcr.io/open-webui/open-webui:main
```

Use the host's **LAN IP**, not `localhost` — inside the container `localhost` is the container.
(For multiple backends the variable is `OPENAI_API_BASE_URLS`, semicolon-separated.)

Browse to `http://<host>:3000` and create the admin account immediately.

---

## Phase 9 — Client configuration

### Claude Code

```bash
# ~/bin/local-claude
#!/usr/bin/env bash
export ANTHROPIC_BASE_URL=http://clode.deep13.lol:8080
export ANTHROPIC_AUTH_TOKEN=local
unset ANTHROPIC_API_KEY            # unset, NOT set-to-empty — see below

export ANTHROPIC_MODEL=coder
export ANTHROPIC_SMALL_FAST_MODEL=coder

# Claude Code assumes 200k for unrecognised model IDs. Derived from usable
# context PER SLOT (-c divided by -np), then held BELOW it — never equal.
export CLAUDE_CODE_AUTO_COMPACT_WINDOW=98304   # 75% of 131072

# Uncomment if llama-server returns 400 on these
# export CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1
# export CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1

exec claude "$@"
```

```bash
chmod +x ~/bin/local-claude
```

A set `ANTHROPIC_API_KEY` silently sends traffic to the real Anthropic API — billed, and off-LAN.
Use `unset` rather than `export ANTHROPIC_API_KEY=`: an empty value can still win its slot in
credential resolution, so absent is safer than blank. Keep this in a wrapper script so normal
`claude` is unaffected.

**`CLAUDE_CODE_AUTO_COMPACT_WINDOW` is derived from usable context *per slot* — `-c` divided by
`-np`, not `-c` itself — and must be set BELOW it, never equal.** `coder` runs `-c 131072 -np 1`,
so per-slot is 131072 and the window is **98304** (75%). If you change either `-c` or `-np` in
`/etc/llama-swap/config.yaml`, recompute both. Gateway model discovery does not help here — it
reads only `id` and `display_name`, carries no context-window field, and ignores model IDs that
don't start with `claude` or `anthropic`.

⚠️ **Equal is not good enough, and this cost an evening on 2026-08-02.** With the window set to
65536 against a 65536 ceiling, the compaction budget and the hard limit are the same number:
auto-compact fires with no room left to run in, and `/compact` fails too because compaction is
itself a request that must fit inside the window it is freeing.

```
API Error: 400 request (65873 tokens) exceeds the available context size (65536 tokens)
Error during compaction: 400 request (66585 tokens) exceeds the available context size (65536)
```

Nothing rescues you from this: Claude Code's *reactive* compaction matches "prompt too long"
against Anthropic's error phrasing, and llama.cpp's wording isn't in that set, so the overflow is
never recognised. The proactive threshold is the only protection there is — leave it slack.

⚠️ **This wrapper's exports beat your shell.** Exporting a different value before running
`local-claude` has no effect; the script overwrites it. Edit the script (or
`clients_auto_compact_window` in Ansible) instead.

`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` (1–100) is the alternative lever — leave the window at the true
per-slot figure and move the trigger percentage down instead.

Verify after a long session with `/context` — it should report a ceiling of 128k, not 200k.

### Aider

```bash
export OPENAI_API_BASE=http://clode.deep13.lol:8080/v1
export OPENAI_API_KEY=local
aider --model openai/coder --edit-format diff
```

`.aider.model.settings.yml` in the repo:

```yaml
- name: openai/coder
  edit_format: diff
  use_repo_map: true
  extra_params:
    max_input_tokens: 65536
```

If you see repeated "SEARCH block not found", switch to `--edit-format whole`.

---

## Phase 10 — Lock it down

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow proto tcp from 192.168.0.0/16 to any port 22,8080,3000
sudo ufw enable
sudo ufw status verbose
```

`proto tcp` must come **before** `from`, and the protocol is mandatory when listing multiple
ports. Adjust the subnet to match your LAN. Do not port-forward any of these.

---

## Post-install verification

```bash
numactl --hardware                                    # 2 nodes, 32 GB each
sudo dmidecode -t memory | grep -i configured         # 2133 MT/s
nvidia-smi                                            # RTX 2080, 8 GB
zpool status                                          # ONLINE, no errors
systemctl is-active llama-swap docker                 # active
curl -s localhost:8080/v1/models | jq -r '.data[].id' # coder, scorer, small
```

---

## Routine maintenance

| Task | Cadence | Command |
|---|---|---|
| ZFS scrub review | Monthly | `zpool status -v tank` |
| SMART trend on the 8 TB | Monthly | `sudo smartctl -a /dev/sdX \| grep -E '^  (5\|187\|188\|197\|198) '` |
| Verify ZFS after kernel update | Every kernel bump | `modinfo zfs && zpool status` |
| Re-baseline bandwidth | After any RAM change | `mbw -q -n 10 1024 \| tail -3` |
| Sync eval data off-box | Ongoing | By design nothing here is durable: `tank` is models-only, boot SSD isn't a home for results |
