#!/usr/bin/env python3
# docksmith/runtime.py
# ============================================================
#  PRANAV - Container Runtime & Process Isolation
#  Full isolation: chroot + Linux namespaces (requires root)
#  User-namespace fallback: chroot + namespaces without root
#  WSL2 fallback: runs command in rootfs via subprocess
# ============================================================

import os
import sys
import subprocess
import ctypes
import ctypes.util

CLONE_NEWNS   = 0x00020000   # mount namespace
CLONE_NEWPID  = 0x20000000   # PID namespace
CLONE_NEWUTS  = 0x04000000   # hostname namespace
CLONE_NEWIPC  = 0x08000000   # IPC namespace
CLONE_NEWNET  = 0x40000000   # network namespace
CLONE_NEWUSER = 0x10000000   # user namespace  ← NEW: enables non-root isolation
MS_PRIVATE    = (1 << 18)
MS_REC        = (1 << 14)


def _is_root() -> bool:
    return os.geteuid() == 0


def _get_libc():
    libc_name = ctypes.util.find_library("c")
    return ctypes.CDLL(libc_name, use_errno=True)


def _unshare(flags: int):
    libc = _get_libc()
    ret  = libc.unshare(ctypes.c_int(flags))
    if ret != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), "unshare()")


def _write_id_map(pid: int, uid: int, gid: int):
    """
    Write uid_map / gid_map so the user namespace root (uid 0 inside)
    maps to the real calling user (uid outside).
    Required for CLONE_NEWUSER to allow chroot without root.
    """
    try:
        with open(f"/proc/{pid}/uid_map", "w") as f:
            f.write(f"0 {uid} 1\n")
    except Exception:
        pass
    try:
        # Must write "deny" to setgroups before writing gid_map
        with open(f"/proc/{pid}/setgroups", "w") as f:
            f.write("deny\n")
        with open(f"/proc/{pid}/gid_map", "w") as f:
            f.write(f"0 {gid} 1\n")
    except Exception:
        pass


def _run_isolated(rootfs: str, command: list, env: dict, workdir: str) -> int:
    """
    Full isolation path (root OR user-namespace):
    fork → unshare namespaces → chroot → exec

    Now uses CLONE_NEWUSER so non-root users also get real chroot isolation.
    """
    real_uid = os.getuid()
    real_gid = os.getgid()

    # Pipe used by child to wait until parent writes uid_map/gid_map
    r_fd, w_fd = os.pipe()

    pid = os.fork()
    if pid == 0:
        # --- CHILD ---
        os.close(w_fd)
        try:
            # Unshare all meaningful namespaces.
            # CLONE_NEWUSER lets non-root processes create isolated namespaces.
            ns_flags = CLONE_NEWNS | CLONE_NEWPID | CLONE_NEWUTS | CLONE_NEWIPC | CLONE_NEWUSER
            try:
                _unshare(ns_flags)
            except OSError:
                # Fallback: try without NEWPID (some kernels restrict it)
                try:
                    _unshare(CLONE_NEWNS | CLONE_NEWUSER)
                except OSError:
                    pass

            # Wait for parent to write uid/gid maps
            os.read(r_fd, 1)
            os.close(r_fd)

            # Make all mounts private so host doesn't see our changes
            try:
                libc = _get_libc()
                libc.mount(b"none", b"/", None, ctypes.c_ulong(MS_REC | MS_PRIVATE), None)
            except Exception:
                pass

            # chroot into the container rootfs — now allowed even without root
            # because we're uid 0 inside the user namespace
            os.chroot(rootfs)
            os.chdir("/")

            # Mount /proc for process listing tools like 'ps'
            try:
                os.makedirs("/proc", exist_ok=True)
                libc = _get_libc()
                # mount(source="proc", target="/proc", filesystemtype="proc", mountflags=0, data=None)
                libc.mount(b"proc", b"/proc", b"proc", ctypes.c_ulong(0), None)
            except Exception:
                pass

            effective_wd = workdir or "/"
            try:
                os.chdir(effective_wd)
            except FileNotFoundError:
                os.makedirs(effective_wd, exist_ok=True)
                os.chdir(effective_wd)

            full_env = dict(env)
            full_env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
            full_env.setdefault("HOME", "/root")
            full_env.setdefault("TERM", "xterm")

            os.execvpe(command[0], command, full_env)
        except Exception as e:
            print(f"[RUNTIME ERROR] {e}", file=sys.stderr)
            os._exit(1)
        os._exit(0)
    else:
        # --- PARENT ---
        os.close(r_fd)
        # Write uid/gid maps so child becomes uid 0 in its user namespace
        _write_id_map(pid, real_uid, real_gid)
        # Unblock child
        os.write(w_fd, b"\x00")
        os.close(w_fd)

        _, status = os.waitpid(pid, 0)
        if os.WIFEXITED(status):
            return os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            return 128 + os.WTERMSIG(status)
        return 1


def _run_wsl2_fallback(rootfs: str, command: list, env: dict, workdir: str) -> int:
    """
    WSL2 / non-root fallback when user namespaces are also unavailable:
    Runs the command directly on the HOST with cwd = rootfs/<workdir>.
    No chroot — but sufficient for demo/testing purposes.
    """
    effective_wd = workdir.lstrip("/") if workdir else ""
    cwd = os.path.join(rootfs, effective_wd) if effective_wd else rootfs
    os.makedirs(cwd, exist_ok=True)

    full_env = os.environ.copy()
    full_env.update(env)
    full_env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:" + full_env.get("PATH", "")

    if len(command) >= 3 and command[0] in ("/bin/sh", "sh") and command[1] == "-c":
        shell_cmd = command[2]
    else:
        shell_cmd = " ".join(command)

    try:
        result = subprocess.run(
            shell_cmd,
            shell=True,
            cwd=cwd,
            env=full_env,
        )
        return result.returncode
    except Exception as e:
        print(f"[RUNTIME ERROR] fallback run failed: {e}", file=sys.stderr)
        return 1


def _user_ns_supported() -> bool:
    """Check if unprivileged user namespaces are allowed on this kernel."""
    # Linux 3.8+ supports user namespaces; some distros disable via sysctl
    try:
        with open("/proc/sys/kernel/unprivileged_userns_clone") as f:
            return f.read().strip() == "1"
    except FileNotFoundError:
        # File absent → distro doesn't restrict it, assume supported
        return True


def isolate_and_run(
    rootfs: str,
    command: list,
    env: dict,
    workdir: str = "/",
) -> int:
    """
    Main entry point called by builder.py (RUN) and main.py (docksmith run).

    Isolation tier selection:
      1. Root available          → full chroot + all namespaces
      2. User namespaces allowed → chroot + namespaces via CLONE_NEWUSER (no root needed)
      3. Neither                 → WSL2 host-fallback (no real isolation)
    """
    if _is_root():
        print("  [isolation] root mode: full chroot + namespace isolation", flush=True)
        return _run_isolated(rootfs, command, env, workdir)
    elif _user_ns_supported():
        print("  [isolation] user-namespace mode: chroot + namespaces (no root needed)", flush=True)
        return _run_isolated(rootfs, command, env, workdir)
    else:
        print("  [isolation] non-root + no user-ns: using WSL2 fallback mode (no chroot)", flush=True)
        return _run_wsl2_fallback(rootfs, command, env, workdir)