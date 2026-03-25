# Docksmith — Execution Manual

> **Requirements:** Linux, Go 1.21+, root privileges (`sudo`).
> Namespace isolation (`CLONE_NEWPID`, `CLONE_NEWNS`, `CLONE_NEWUTS`) requires running as root on Linux.

---

## 1. Install Go (if not already installed)

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y golang-go

# Or install the latest version manually
wget https://go.dev/dl/go1.22.linux-amd64.tar.gz
sudo tar -C /usr/local -xzf go1.22.linux-amd64.tar.gz
export PATH=$PATH:/usr/local/go/bin
```

Verify:
```bash
go version
# go version go1.22.x linux/amd64
```

---

## 2. Clone and Build

```bash
git clone <repo-url>
cd Team_11_G_Docksmith

# Compile both binaries into the project root
go build -o docksmith ./cmd/docksmith
go build -o setup-base ./cmd/setup-base
```

---

## 3. Import a Base Image

Docksmith has no network access during build or run. You must import a base image once before any build.

### Option A — From a rootfs tar (recommended)

Download an Alpine Linux minimal rootfs:
```bash
wget https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-minirootfs-3.19.1-x86_64.tar.gz
```

Import it:
```bash
sudo ./setup-base --image alpine:latest --rootfs-tar alpine-minirootfs-3.19.1-x86_64.tar.gz
```

### Option B — From an unpacked rootfs directory

```bash
# Export from Docker if available
docker export $(docker create alpine:latest) | tar -C /tmp/alpine-rootfs -xf -

sudo ./setup-base --image alpine:latest --rootfs-dir /tmp/alpine-rootfs
```

Expected output:
```
Imported base image alpine:latest (sha256:a3b2c1...)
```

Base images are stored in `~/.docksmith/images/` and `~/.docksmith/layers/`.

---

## 4. Build the Sample App

```bash
sudo ./docksmith build -t myapp:latest ./sample_app
```

Expected output (first build — all cache misses):
```

Step 1/6 : FROM alpine:latest
Step 2/6 : WORKDIR /app
Step 3/6 : ENV APP_MESSAGE=Hello_from_Docksmith
Step 4/6 : COPY . /app [CACHE MISS] 0.12s
Step 5/6 : RUN chmod +x /app/run.sh [CACHE MISS] 0.08s
Step 6/6 : CMD ["/app/run.sh"]

Successfully built sha256:d4f9de... myapp:latest (0.23s)
```

Rebuild immediately (all cache hits):
```bash
sudo ./docksmith build -t myapp:latest ./sample_app
```

Expected output:
```

Step 1/6 : FROM alpine:latest
Step 2/6 : WORKDIR /app
Step 3/6 : ENV APP_MESSAGE=Hello_from_Docksmith
Step 4/6 : COPY . /app [CACHE HIT]
Step 5/6 : RUN chmod +x /app/run.sh [CACHE HIT]
Step 6/6 : CMD ["/app/run.sh"]

Successfully built sha256:d4f9de... myapp:latest (0.01s)
```

Force a full rebuild with no cache:
```bash
sudo ./docksmith build --no-cache -t myapp:latest ./sample_app
```

---

## 5. List Images

```bash
sudo ./docksmith images
```

Output:
```
NAME                 TAG          ID             CREATED
myapp                latest       sha256:d4f9de  2024-01-15T10:30:00Z
alpine               latest       sha256:a3b2c1  2024-01-15T10:00:00Z
```

---

## 6. Run a Container

```bash
sudo ./docksmith run myapp:latest
```

Expected output:
```
Hello from Docksmith!
APP_MESSAGE = Hello_from_Docksmith
Container exited with code 0
```

### With environment variable override

```bash
sudo ./docksmith run -e APP_MESSAGE=overridden myapp:latest
```

Expected output:
```
Hello from Docksmith!
APP_MESSAGE = overridden
Container exited with code 0
```

### With command override

```bash
sudo ./docksmith run myapp:latest /bin/sh -c "echo hello from override"
```

---

## 7. Verify Filesystem Isolation (Demo Check)

Prove that a file written inside a container does NOT appear on the host:

```bash
# Write a file inside the container
sudo ./docksmith run myapp:latest /bin/sh -c "echo secret > /isolation_test.txt && echo written"

# Verify it does NOT exist on the host
ls /isolation_test.txt 2>/dev/null && echo "FAIL: file leaked!" || echo "PASS: file not on host"
```

Expected:
```
written
Container exited with code 0
PASS: file not on host
```

This works because `CLONE_NEWNS` gives the container its own mount namespace — writes are scoped to the container's temporary rootfs directory, which is deleted after the container exits.

---

## 8. Remove an Image

```bash
sudo ./docksmith rmi myapp:latest
```

Output:
```
Removed image myapp:latest
```

This deletes the manifest JSON and all associated layer tar files from `~/.docksmith/`.

---

## 9. Full Demo Sequence (as per spec)

```bash
# 1. Cold build — all CACHE MISS
sudo ./docksmith build -t myapp:latest ./sample_app

# 2. Warm rebuild — all CACHE HIT, near-instant
sudo ./docksmith build -t myapp:latest ./sample_app

# 3. Edit a source file and rebuild — partial cache invalidation
echo "# changed" >> sample_app/app.py
sudo ./docksmith build -t myapp:latest ./sample_app
# Steps above the changed COPY → CACHE HIT
# Changed step and all below → CACHE MISS

# 4. List images
sudo ./docksmith images

# 5. Run container — visible output
sudo ./docksmith run myapp:latest

# 6. ENV override
sudo ./docksmith run -e APP_MESSAGE=demo myapp:latest

# 7. Isolation check — file written inside container must NOT appear on host
sudo ./docksmith run myapp:latest /bin/sh -c "echo secret > /isolation_test.txt"
ls /isolation_test.txt 2>/dev/null || echo "PASS: not on host"

# 8. Remove image
sudo ./docksmith rmi myapp:latest
```

---

## 10. State Directory Layout

All data is stored in `~/.docksmith/` (or `$DOCKSMITH_HOME` if set):

```
~/.docksmith/
├── images/         # JSON manifest per image  e.g. myapp:latest.json
├── layers/         # Content-addressed tar files  named by SHA-256 hex
└── cache/          # Cache index  key-hex → layer-digest
```

To wipe all state:
```bash
rm -rf ~/.docksmith
```

---

## 11. Custom Base Image Name

```bash
sudo ./setup-base --image mybase:1.0 --rootfs-tar my-rootfs.tar.gz

# Then in Docksmithfile:
# FROM mybase:1.0
```

---

## Troubleshooting

| Error | Fix |
|---|---|
| `operation not permitted` | Run with `sudo` — namespaces require root |
| `FROM: image 'alpine:latest' not found` | Run `setup-base` first to import the base image |
| `no files matched` in COPY | Check the `src` path is relative to the context directory |
| `RUN failed (exit 127)` | Command not found inside container — check the base image has the binary |
| `No command provided and image has no CMD` | Add `CMD [...]` to your Docksmithfile or pass a command to `run` |
