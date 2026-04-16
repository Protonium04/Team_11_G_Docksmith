# 🚢 Docksmith — Cloud Computing Mini Project

A minimal container build system implemented in Python, inspired by Docker.

---

## 👥 Team Breakdown

| File(s) | Owner | What it does |
|---|---|---|
| `docksmith/models.py`, `state.py`, `main.py` | **Piyush** | Dataclasses, manifest I/O, all 4 CLI commands |
| `docksmith/parser.py`, `layers.py`, `builder.py` | **Protham** | Docksmithfile parser, tar layer creation, build orchestrator |
| `docksmith/cache.py`, `reporter.py`, `dashboard/data_gen.py` | **Preksha** | Cache key computation, hit/miss logic, dashboard data generator |
| `docksmith/runtime.py`, `setup_base_image.py`, `sample_app/` | **Pranav** | Linux process isolation, base image import, sample app |

---

## 📁 Folder Structure

```
docksmith_project/
├── requirements.txt
├── README.md
├── setup_base_image.py          ← PRANAV: run once before any builds
├── setup.py
│
├── docksmith/
│   ├── __init__.py
│   ├── models.py                ← PIYUSH
│   ├── state.py                 ← PIYUSH
│   ├── main.py                  ← PIYUSH  (CLI: build, images, rmi, run)
│   ├── parser.py                ← PROTHAM
│   ├── layers.py                ← PROTHAM
│   ├── builder.py               ← PROTHAM
│   ├── cache.py                 ← PREKSHA
│   ├── reporter.py              ← PREKSHA
│   ├── runtime.py               ← PRANAV
│   └── paths.py                 (shared constants)
│
├── tests/
│   ├── test_parser.py           ← PROTHAM tests
│   ├── test_layers.py           ← PROTHAM tests
│   ├── test_builder.py          ← PROTHAM tests
│   ├── test_cache.py            ← PREKSHA tests
│   └── test_reporter.py        ← PREKSHA tests
│
├── sample_app/                  ← PRANAV
│   ├── Docksmithfile
│   ├── app.py
│   └── run.sh
│
└── dashboard/                   ← PREKSHA
    ├── dashboard.html
    ├── data_gen.py
    └── data.json
```

---

## ⚠️ Requirements

- **Linux only** (Ubuntu in WSL2 or VirtualBox VM on Windows 11)
- Python 3.10+
- Root/sudo for namespace isolation (`docksmith run` and `RUN` during build)

---

## 🚀 Setup & Run — Step by Step

### Step 1 — Enable WSL2 (PowerShell as Admin, Windows only)
```powershell
wsl --install
wsl --set-default-version 2
```
Restart PC. Then open VSCode → `Ctrl+Shift+P` → **WSL: Connect to WSL**.

### Step 2 — Install Python & dependencies (WSL2 terminal)
```bash
sudo apt update && sudo apt install python3 python3-pip python3-venv -y
cd ~/docksmith_project
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 3 — Import base images (run ONCE — Pranav's script)
```bash
# With Docker available (recommended):
python3 setup_base_image.py

# Without Docker (stub mode for testing):
python3 setup_base_image.py
```

### Step 4 — Build the sample app
```bash
python3 -m docksmith build -t sampleapp:latest sample_app
```

### Step 5 — List images
```bash
python3 -m docksmith images
```

### Step 6 — Run the container
```bash
sudo python3 -m docksmith run sampleapp:latest
# With env override:
sudo python3 -m docksmith run -e GREETING=Namaste sampleapp:latest
```

### Step 7 — Test the cache (rebuild — should hit cache)
```bash
python3 -m docksmith build -t sampleapp:latest sample_app
# All steps should show [CACHE HIT]
```

### Step 8 — Force a full rebuild
```bash
python3 -m docksmith build --no-cache -t sampleapp:latest sample_app
# All steps show [CACHE MISS]
```

### Step 9 — Remove an image
```bash
python3 -m docksmith rmi sampleapp:latest
```

---

## 🖥️ Dashboard

After building at least one image, generate the dashboard data and open in browser:

```bash
python3 dashboard/data_gen.py
# Then open dashboard/dashboard.html in your browser (double-click or use Live Server in VSCode)
```

The dashboard auto-refreshes every 10 seconds.

---

## 🧪 Running Tests

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run per-person tests
python3 -m pytest tests/test_parser.py tests/test_layers.py tests/test_builder.py -v   # Protham
python3 -m pytest tests/test_cache.py tests/test_reporter.py -v                         # Preksha
```

---

## 🔑 Important Notes

1. **`docksmith run` and RUN during build require `sudo`** — Linux namespace isolation needs elevated privileges in WSL2.
2. **Base images must be imported before the first build** — run `setup_base_image.py` first.
3. **All work happens inside WSL2** — never run Python commands in PowerShell.
4. **VSCode tip** — install the "WSL" extension and connect via `WSL: Connect to WSL` so the terminal runs inside Linux.

---

## 🎯 Demo Checklist (8 Scenarios)

- [ ] First build — all steps `[CACHE MISS]`
- [ ] Second build (no changes) — all steps `[CACHE HIT]`
- [ ] Change a source file → only that step and downstream are `[CACHE MISS]`
- [ ] `--no-cache` flag → all steps `[CACHE MISS]`
- [ ] `docksmith images` shows correct name/tag/digest/layers
- [ ] `docksmith rmi` removes image and exclusive layers
- [ ] `docksmith run -e KEY=VALUE` overrides env correctly
- [ ] File written inside container does NOT appear on host (isolation check)
