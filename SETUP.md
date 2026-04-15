# Docksmith — Setup & Demo Manual

Run this inside **WSL2 Ubuntu/Debian** (or any native Linux). macOS works too for everything except the namespace isolation demo, which is Linux-only.

---

## 1. Prerequisites

```bash
sudo apt update
sudo apt install -y python3 python3-click python3-venv curl
python3 --version     # must be 3.10+
```

If `python3-click` is not available on your distro, use a venv:

```bash
cd /path/to/repo
python3 -m venv .venv
source .venv/bin/activate
pip install click
```

and prefix every subsequent command with `./.venv/bin/python` instead of `python3`.

---

## 2. Clone into your Linux home directory

Do **not** run from `/mnt/c/...` on WSL — NTFS strips Unix permissions and breaks reproducible tar digests.

```bash
cd ~
git clone <repo-url> docksmith
cd ~/docksmith
```

---

## 3. Download and import a base image (one-time, online)

Docksmith needs at least one base image in its local store before any build. Alpine is tiny and bundled with `/bin/sh`, so we use that.

```bash
mkdir -p ~/alpine-rootfs
curl -L -o /tmp/alpine.tar.gz \
  https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-minirootfs-3.19.0-x86_64.tar.gz
sudo tar -xzf /tmp/alpine.tar.gz -C ~/alpine-rootfs

# Sanity check — must exist
ls ~/alpine-rootfs/bin/sh
```

Import it into `~/.docksmith/` as the `alpine:latest` image:

```bash
cd ~/docksmith
sudo HOME=$HOME python3 setup_base_image.py --image alpine:latest --rootfs-dir ~/alpine-rootfs
sudo chown -R $USER:$USER ~/.docksmith
```

> **Why `sudo HOME=$HOME`?** The alpine rootfs is root-owned, so tar creation needs sudo. Passing `HOME=$HOME` preserves your user's home directory so the state lands in `/home/you/.docksmith` instead of `/root/.docksmith`.

Verify:

```bash
python3 -m docksmith.main images
# NAME    TAG     IMAGE ID        CREATED
# alpine  latest  <12 hex chars>  <timestamp>
```

From here on, nothing touches the network.

---

## 4. Run the test suite (optional sanity check)

```bash
python3 -m pytest tests/ -q
# 75 passed
```

---

## 5. Demo flow (matches the project rubric)

### 5.1 Cold build

```bash
python3 -m docksmith.main build -t myapp:latest sample_app
```

Expect both `COPY` and `RUN` to show `[CACHE MISS]`, total time printed.

### 5.2 Warm build — cache hit + reproducible digest

```bash
python3 -m docksmith.main build -t myapp:latest sample_app
```

Both layer-producing steps now show `[CACHE HIT]` and the final `sha256:...` **must match** the cold-build digest (proves the `created` timestamp was preserved).

### 5.3 Edit source, rebuild — cascade invalidation

```bash
echo "# tweak $(date +%s)" >> sample_app/run.sh
python3 -m docksmith.main build -t myapp:latest sample_app
```

Step 4 (`COPY`) and step 5 (`RUN`) both show `[CACHE MISS]` (cascade). WORKDIR/ENV/CMD steps above still reuse their config unchanged.

### 5.4 List images

```bash
python3 -m docksmith.main images
```

### 5.5 Run the container (default CMD)

```bash
sudo HOME=$HOME python3 -m docksmith.main run myapp:latest
```

Expected output:
```
Hello from Docksmith sample app
APP_NAME=Docksmith
BUILD_MARKER=build-ok
```

### 5.6 Run with `-e` override

```bash
sudo HOME=$HOME python3 -m docksmith.main run -e APP_NAME=OverriddenValue myapp:latest
```

`APP_NAME=OverriddenValue` appears — the `-e` flag takes precedence over the image's `ENV`.

### 5.7 Isolation pass/fail (the demo gate)

Write a file **inside** the container, then check the host:

```bash
sudo HOME=$HOME python3 -m docksmith.main run myapp:latest -- \
  /bin/sh -c 'echo INSIDE > /tmp/container_sentinel && ls -la /tmp/container_sentinel'

# Back on the host:
ls /tmp/container_sentinel
# → "No such file or directory"  ✓ ISOLATION PASSES
```

Also confirm host paths are invisible:

```bash
sudo HOME=$HOME python3 -m docksmith.main run myapp:latest -- /bin/sh -c 'ls /home 2>&1; ls /mnt 2>&1'
# → both empty / "No such file or directory"
```

### 5.8 Remove the image

```bash
python3 -m docksmith.main rmi myapp:latest
python3 -m docksmith.main images        # myapp gone
ls ~/.docksmith/layers                   # only the alpine layer remains (or empty if alpine shared a layer)
```

> Per the rubric, `rmi` does **not** reference-count. Deleting an image removes its layer files even if another image references the same digest.

---

## 6. Dashboard (optional, nice for demo)

The dashboard is static HTML that reads `dashboard/data.json`. Regenerate after every build/rmi, then refresh the browser.

**Terminal A — HTTP server:**

```bash
cd ~/docksmith/dashboard
python3 -m http.server 8000
```

**Terminal B — build and regenerate:**

```bash
cd ~/docksmith
python3 -m docksmith.main build -t hello:v1 sample_app --no-cache
python3 dashboard/data_gen.py
```

Open `http://localhost:8000/dashboard.html` in your browser and refresh after each rebuild.

---

## 7. Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `pip install click` → `externally-managed-environment` | Use `sudo apt install -y python3-click` or switch to a venv (see §1) |
| `RUN` step / `run` → `Layer not found` | Cache points to a layer that was deleted. Run `rm -f ~/.docksmith/cache/index.json` and rebuild, or wipe the whole state dir. |
| `Image 'myapp:latest' not found` when using `sudo` | You dropped the `HOME=$HOME`; sudo reset HOME to `/root`. Always use `sudo HOME=$HOME python3 ...`. |
| `Operation not permitted` on `unshare` / container didn't isolate | You skipped `sudo` on `run` / `build`. Namespaces + chroot require root. |
| Warm-build digest differs from cold | You're running under `/mnt/c/...` — NTFS strips permissions and mtimes. Move the repo to `~/docksmith`. |
| `AbsoluteLinkError` during extract | Old extractor using the `data` filter; pull latest `docksmith/layers.py` — it uses the `tar` filter which allows absolute symlinks (alpine has `/bin/sh → /bin/busybox`). |

---

## 8. One-shot demo script

```bash
cd ~/docksmith
sudo rm -rf /root/.docksmith ~/.docksmith
sudo HOME=$HOME python3 setup_base_image.py --image alpine:latest --rootfs-dir ~/alpine-rootfs
sudo chown -R $USER:$USER ~/.docksmith

python3 -m docksmith.main build -t myapp:latest sample_app            # cold — all MISS
python3 -m docksmith.main build -t myapp:latest sample_app            # warm — all HIT
python3 -m docksmith.main images
sudo HOME=$HOME python3 -m docksmith.main run myapp:latest            # default CMD
sudo HOME=$HOME python3 -m docksmith.main run -e APP_NAME=Demo myapp:latest
sudo HOME=$HOME python3 -m docksmith.main run myapp:latest -- /bin/sh -c 'echo X > /tmp/sentinel'
ls /tmp/sentinel                                                       # must NOT exist → ISOLATION PASS
python3 -m docksmith.main rmi myapp:latest
```
