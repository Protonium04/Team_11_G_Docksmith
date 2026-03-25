import os
import shutil
import subprocess
import tempfile

from docksmith.layers import extract_layer
from docksmith.models import ImageManifest


def _parse_env_list(env_items: list[str]) -> dict[str, str]:
    env = {}
    for item in env_items:
        if "=" in item:
            key, _, value = item.partition("=")
            env[key] = value
    return env


def isolate_and_run(
    rootfs: str,
    command: list[str],
    env: dict[str, str] | None = None,
    workdir: str = "/",
) -> int:
    """
    Shared execution primitive used for both build RUN and runtime `docksmith run`.
    On Linux as root, uses chroot isolation. Otherwise, executes in assembled rootfs
    with cwd scoping as a compatibility fallback.
    """
    env = dict(env or {})
    effective_workdir = workdir or "/"

    if os.name == "posix" and hasattr(os, "chroot") and hasattr(os, "geteuid") and os.geteuid() == 0:
        runtime_env = dict(os.environ)
        runtime_env.update(env)

        def _preexec():
            os.chroot(rootfs)
            os.chdir(effective_workdir)

        proc = subprocess.run(
            command,
            preexec_fn=_preexec,
            env=runtime_env,
            check=False,
        )
        return proc.returncode

    # Fallback mode for non-root or non-Linux platforms.
    fallback_cwd = os.path.join(rootfs, effective_workdir.lstrip("/"))
    os.makedirs(fallback_cwd, exist_ok=True)
    runtime_env = dict(os.environ)
    runtime_env.update(env)
    print(
        "[RUNTIME WARNING] Running without Linux chroot isolation "
        "(requires Linux + root privileges)."
    )
    proc = subprocess.run(
        command,
        cwd=fallback_cwd,
        env=runtime_env,
        check=False,
    )
    return proc.returncode


def run_image(
    manifest: ImageManifest,
    command_override: list[str] | None = None,
    env_overrides: dict[str, str] | None = None,
) -> int:
    command = command_override or list(manifest.config.Cmd or [])
    if not command:
        raise RuntimeError(
            "[RUNTIME ERROR] No command provided and image has no CMD."
        )

    image_env = _parse_env_list(list(manifest.config.Env or []))
    merged_env = dict(image_env)
    merged_env.update(env_overrides or {})
    workdir = manifest.config.WorkingDir or "/"

    with tempfile.TemporaryDirectory(prefix="docksmith_run_") as rootfs:
        for layer in manifest.layers:
            extract_layer(layer.digest, rootfs)
        code = isolate_and_run(
            rootfs=rootfs,
            command=command,
            env=merged_env,
            workdir=workdir,
        )

    print(f"Container exited with code {code}")
    return code
