# docksmith/models.py
# ============================================================
#  PIYUSH — Shared dataclasses used by ALL teammates
# ============================================================

from dataclasses import dataclass, field
from typing import List


@dataclass
class LayerEntry:
    digest: str       # "sha256:<hex>"
    size: int         # bytes
    createdBy: str    # "COPY . /app" or "RUN echo hi"


@dataclass
class ImageConfig:
    Env: List[str] = field(default_factory=list)        # ["KEY=value", ...]
    Cmd: List[str] = field(default_factory=list)        # ["python", "main.py"]
    WorkingDir: str = ""


@dataclass
class ImageManifest:
    name: str
    tag: str
    digest: str          # "sha256:<hex>" of the serialised manifest (no digest field)
    created: str         # ISO-8601 UTC string
    config: ImageConfig
    layers: List[LayerEntry] = field(default_factory=list)
