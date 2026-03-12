# 🚢 Docksmith — Project Documentation
### Cloud Computing | Team Project
**Course:** Cloud Computing  
**Project:** Docksmith — A Simplified Docker-like Build & Runtime System  

---

## 👥 Team

| Name | Module |
|------|--------|
| **Piyush** | CLI & State Management |
| **Prathama** | Build Engine & Docksmithfile Parser |
| **Preksha** | Build Cache System |
| **Pranav** | Container Runtime & Process Isolation |

---

## 📌 What Is Docksmith?

Docksmith is a simplified Docker-like container build and runtime system built entirely from scratch — no Docker, no runc, no containerd. It is a single CLI binary that lets you:

1. **Build** container images from a `Docksmithfile` (similar to a `Dockerfile`)
2. **Cache** build steps intelligently and deterministically
3. **Run** containers in full Linux process isolation using raw OS primitives

Everything is stored locally in `~/.docksmith/`. There is no daemon process, no network calls during build or run, and no external container tooling of any kind.

---

## 🗂️ State Directory Layout

```
~/.docksmith/
├── images/      # One JSON manifest file per built image
├── layers/      # Content-addressed tar delta files, named by SHA-256 digest
└── cache/       # Index mapping cache keys → layer digests
```

---

## 🔧 Build Language — The Docksmithfile

Docksmith uses a custom build file called `Docksmithfile`. All six instructions below are implemented. Any unrecognised instruction causes an immediate failure with a clear error and line number.

| Instruction | Behaviour |
|---|---|
| `FROM <image>[:<tag>]` | Load the base image from local store. Use its layers as the starting filesystem. |
| `COPY <src> <dest>` | Copy files from build context into the image. Supports `*` and `**` globs. Creates missing directories. Produces a layer. |
| `RUN <command>` | Execute a shell command inside the assembled image filesystem (not on the host). Produces a layer. |
| `WORKDIR <path>` | Set the working directory for all subsequent instructions. Creates the path silently if it doesn't exist. No layer produced. |
| `ENV <key>=<value>` | Store an environment variable in the image config. Injected into container processes and all `RUN` commands during build. No layer produced. |
| `CMD ["exec","arg"]` | Default command when the container starts (JSON array form). No layer produced. |

**Hard Requirement:** `RUN` commands execute inside the image filesystem using the same Linux isolation used at runtime — never on the host.

---

## 🖼️ Image Format

### Manifest (`~/.docksmith/images/<name>:<tag>.json`)

```json
{
  "name": "myapp",
  "tag": "latest",
  "digest": "sha256:<hash>",
  "created": "<ISO-8601>",
  "config": {
    "Env": ["KEY=value"],
    "Cmd": ["python", "main.py"],
    "WorkingDir": "/app"
  },
  "layers": [
    { "digest": "sha256:aaa...", "size": 2048, "createdBy": "base layer" },
    { "digest": "sha256:bbb...", "size": 4096, "createdBy": "COPY . /app" },
    { "digest": "sha256:ccc...", "size": 8192, "createdBy": "RUN pip install ..." }
  ]
}
```

- The `digest` field is computed by serialising the manifest with `digest: ""`, hashing the bytes with SHA-256, then writing the final file with the actual hash.
- `COPY` and `RUN` each produce a **delta layer** — only files added/modified in that step.
- `FROM`, `WORKDIR`, `ENV`, and `CMD` update config only — no new layer.

---

## ⚡ Build Cache System

The cache makes rebuilds near-instant when nothing has changed.

### Cache Key Inputs (for every `COPY` and `RUN` step):

| Input | Description |
|---|---|
| Previous layer digest | Digest of the last `COPY`/`RUN` layer (or base image manifest digest for the first step) |
| Instruction text | Exact instruction string as written in the Docksmithfile |
| WORKDIR value | Current working directory at the time this instruction is reached |
| ENV state | All accumulated `key=value` pairs, sorted lexicographically |
| COPY source hashes | SHA-256 of each source file's raw bytes, sorted by path (COPY only) |

### Cache Rules:

| Situation | Behaviour |
|---|---|
| Cache hit | Reuse stored layer, skip execution → prints `[CACHE HIT]` |
| Cache miss | Execute, store result, update index → prints `[CACHE MISS]` |
| Any miss | All subsequent steps also become misses (cascade) |
| `--no-cache` flag | Skip all cache lookups and writes; layers still stored normally |

### Invalidation Triggers:

- A `COPY` source file changes
- Instruction text changes
- `FROM` base image changes
- A layer file is missing from disk
- `WORKDIR` or `ENV` value changes at that step

### Reproducible Builds:
Tar entries are added in **lexicographically sorted order** with **file timestamps zeroed**. This ensures the same inputs always produce byte-identical layer digests and manifests.

---

## 🏃 Container Runtime

### How a Container Runs:

1. Extract all layer tar files in order into a temporary directory
2. Apply later layers over earlier ones (files at the same path are overwritten)
3. Isolate a process into that root using **Linux OS primitives** (namespaces + chroot — no Docker/runc)
4. Inject all image `ENV` values; `-e KEY=VALUE` overrides take precedence
5. Set the working directory to `WorkingDir` (defaults to `/`)
6. Execute the command, block until exit, print the exit code
7. Clean up the temporary directory

### Hard Requirements:

- A file written inside a container **must not appear on the host filesystem** — verified live at demo.
- The **same isolation primitive** is used for both `RUN` during build and `docksmith run` at runtime.
- No detached mode — the CLI always blocks until the process exits.

---

## 💻 CLI Reference

```bash
# Build an image from a Docksmithfile in the given context directory
docksmith build -t <name:tag> <context_dir> [--no-cache]

# List all images in the local store
docksmith images

# Remove an image and all its layer files
docksmith rmi <name:tag>

# Run a container from an image
docksmith run <name:tag> [command]
docksmith run -e KEY=VALUE <name:tag> [command]
```

**`docksmith images` output columns:** Name, Tag, ID (first 12 chars of digest), Created

---

## 👤 Piyush: CLI & State Management

### Responsibilities:
- Set up the project repository and overall code structure
- Implement the `~/.docksmith/` directory layout — `images/`, `layers/`, `cache/`
- Implement all four CLI entry points: `build`, `images`, `rmi`, `run`
- Image manifest serialisation and deserialisation (JSON read/write)
- Manifest digest computation (hash canonical form with `digest: ""`, write final with actual hash)
- `docksmith images` — list all manifests with Name, Tag, 12-char ID, Created
- `docksmith rmi` — delete manifest JSON + all referenced layer files from disk
- Wire all subsystems together: CLI calls into the Build Engine (Protham) and Container Runtime (Pranav)
- `--no-cache` flag plumbing through to the cache subsystem
- `-e KEY=VALUE` flag plumbing through to the runtime

### Key Interfaces Owned:
- Manifest struct / schema
- Disk I/O helpers for `images/` and `layers/`
- Top-level command dispatch

---

## 👤 Prathama: Build Engine & Docksmithfile Parser

### Responsibilities:
- Parse `Docksmithfile` line by line — all six instructions
- Fail immediately with a clear error and line number on any unrecognised instruction
- `FROM` — load base image manifest from local store; inherit its layers; fail clearly if not found
- `COPY` — resolve `*` / `**` glob patterns against the build context; create missing destination directories; produce a delta tar layer
- `RUN` — assemble the filesystem so far; execute the command inside it via Pranav's isolation primitive; capture the resulting filesystem delta as a new tar layer
- `WORKDIR` — update working directory state; silently create the path in the temp filesystem if it doesn't exist; no layer produced
- `ENV` — accumulate key-value pairs in image config; inject into `RUN` commands during build; no layer produced
- `CMD` — store default command array in image config; no layer produced
- Tar creation rules: **entries sorted lexicographically**, **all file timestamps zeroed** (critical for reproducibility and cache correctness)
- Layer storage: write tar to `layers/` named by its SHA-256 digest; skip write if digest already exists

### Key Interfaces Owned:
- `Docksmithfile` parser
- Layer tar creation and storage
- Build step orchestration (calls Preksha's cache lookup before each step)

---

## 👤 Preksha: Build Cache System

### Responsibilities:
- Implement the full cache key computation algorithm (deterministic SHA-256 hash of all inputs listed above)
- Cache index: `cache/` directory stores mappings from cache key → layer digest
- Cache lookup: before every `COPY` or `RUN`, check if the key exists in the index and the layer file is present on disk
- On cache hit: return the stored layer digest, print `[CACHE HIT]`
- On cache miss: signal the build engine to execute, receive the new layer digest, update the index, print `[CACHE MISS]`
- Cascade logic: once any step misses, set a flag that forces all subsequent steps to miss regardless
- `--no-cache` mode: bypass all lookups and writes entirely
- Step timing: record wall-clock duration for each layer-producing step, print after cache status (e.g., `[CACHE MISS] 3.82s`)
- **Created timestamp preservation:** on a fully cache-hit rebuild, rewrite the manifest with the original `created` value so the manifest digest is identical across rebuilds

### Key Interfaces Owned:
- Cache key hash function
- Cache index read/write
- Build output formatting (`Step N/M : INSTRUCTION [CACHE HIT/MISS] Xs`)

---

## 👤 Pranav: Container Runtime & Process Isolation

### Responsibilities:
- Implement Linux process isolation using raw OS primitives:
  - `clone(2)` / `unshare(2)` with `CLONE_NEWPID`, `CLONE_NEWNS`, `CLONE_NEWUTS`
  - `chroot(2)` or `pivot_root(2)` into the assembled layer directory
  - **No Docker, runc, containerd, or any other container tool**
- Expose a single isolation primitive reused in two places:
  - `RUN` during build (called by Protham's build engine)
  - `docksmith run` at runtime (called by Piyush's CLI)
- `docksmith run` full flow: extract all layers in order → isolate → inject ENV + WorkingDir → exec → wait → print exit code → cleanup temp dir
- Handle `-e KEY=VALUE` overrides (take precedence over image ENV)
- Default to `WorkingDir: /` if not specified in the image config
- Fail with a clear error if no `CMD` is defined and no command is provided at runtime
- **Write the one-time base image import script** — download a minimal Linux base image (e.g., Alpine), import it into `~/.docksmith/` before any build is attempted
- **Build the sample app** — a `Docksmithfile` that uses all six instructions, has bundled dependencies, produces visible output, and supports `-e` override at runtime

### Key Interfaces Owned:
- Process isolation primitive (shared by build and run)
- Layer extraction and temp root assembly
- Base image import tooling
- Sample application and Docksmithfile

---

## 🔗 Integration Points

| Interface | Who Produces | Who Consumes |
|---|---|---|
| Manifest JSON schema | Piyush | Protham, Preksha, Pranav |
| Layer tar format (sorted, zeroed timestamps) | Protham | Pranav (extraction), Preksha (hashing) |
| Cache lookup API | Preksha | Protham (before each COPY/RUN) |
| Isolation primitive | Pranav | Protham (for RUN during build) |
| Base image in `~/.docksmith/` | Pranav | Protham (FROM instruction) |

---

## 🧪 Demo Checklist

| # | Command | What It Demonstrates |
|---|---|---|
| 1 | `docksmith build -t myapp:latest .` (cold) | All steps show `[CACHE MISS]`, total time printed |
| 2 | `docksmith build -t myapp:latest .` (warm) | All steps show `[CACHE HIT]`, near-instant |
| 3 | Edit a source file, rebuild | Changed step and all below → `[CACHE MISS]`; above steps → `[CACHE HIT]` |
| 4 | `docksmith images` | Correct Name, Tag, 12-char ID, Created timestamp |
| 5 | `docksmith run myapp:latest` | Container starts, produces visible output, exits cleanly |
| 6 | `docksmith run -e KEY=newVal myapp:latest` | ENV override applied correctly inside container |
| 7 | Write a file inside container, check host | **PASS**: file must NOT appear anywhere on the host filesystem |
| 8 | `docksmith rmi myapp:latest` | Manifest and all associated layer files removed from `~/.docksmith/` |

---

## ⚠️ Critical Constraints

| Constraint | Detail |
|---|---|
| No network during build/run | All base images downloaded once at setup; everything else offline |
| No existing runtimes | No Docker, runc, containerd — isolation via raw OS syscalls only |
| Immutable layers | Once written, a layer is never modified; stored once per digest |
| Same isolation for build & run | One primitive, used in both places — not two separate approaches |
| Reproducible builds | Sorted tar entries + zeroed timestamps = identical digests for identical inputs |
| Manifest timestamp | `created` field preserved on full cache-hit rebuilds so manifest digest is stable |

---

## 🛠️ Recommended Tech Stack

**Go** — single binary, excellent `syscall`/`golang.org/x/sys/unix` packages for namespace isolation, solid stdlib for tar, SHA-256, and JSON. Python is possible but OS-level isolation is more complex.

---

## 📁 Sample App Requirements

The sample app included in the repo must:
- Use **all six instructions**: `FROM`, `COPY`, `RUN`, `WORKDIR`, `ENV`, `CMD`
- Reference a pre-imported base image via `FROM`
- Have **all dependencies bundled** — no network access during build or run
- Produce **visible output** when run
- Support at least one `ENV` value overridable via `-e` at runtime
