from dataclasses import dataclass, field


@dataclass
class LayerEntry:
    digest: str
    size: int
    createdBy: str


@dataclass
class ImageConfig:
    Env: list[str] = field(default_factory=list)
    Cmd: list[str] = field(default_factory=list)
    WorkingDir: str = ""


@dataclass
class ImageManifest:
    name: str
    tag: str
    digest: str
    created: str
    config: ImageConfig
    layers: list[LayerEntry] = field(default_factory=list)
