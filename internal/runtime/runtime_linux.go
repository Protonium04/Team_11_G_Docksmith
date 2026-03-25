//go:build linux

package runtime

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"

	"docksmith/internal/layers"
	"docksmith/internal/models"
)

// IsolateAndRun executes command inside rootfs with Linux namespace isolation.
// Uses CLONE_NEWPID | CLONE_NEWNS | CLONE_NEWUTS + chroot.
// Must be run as root.
func IsolateAndRun(rootfs string, command []string, env map[string]string, workdir string) (int, error) {
	if workdir == "" {
		workdir = "/"
	}

	// Build environment slice
	envSlice := os.Environ()
	for k, v := range env {
		envSlice = append(envSlice, k+"="+v)
	}

	// Bind /proc, /dev, /sys into rootfs if they exist in the host
	// so that commands like `sh` can function properly inside the container.
	for _, special := range []string{"proc", "dev", "sys"} {
		hostDir := "/" + special
		containerDir := filepath.Join(rootfs, special)
		if _, err := os.Stat(hostDir); err == nil {
			os.MkdirAll(containerDir, 0755)
		}
	}

	cmd := exec.Command(command[0], command[1:]...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Env = envSlice
	cmd.Dir = rootfs // initial dir before chroot

	cmd.SysProcAttr = &syscall.SysProcAttr{
		Cloneflags: syscall.CLONE_NEWPID | syscall.CLONE_NEWNS | syscall.CLONE_NEWUTS,
		Chroot:     rootfs,
	}

	// Set working dir relative to rootfs (will be applied after chroot)
	if workdir != "/" {
		// We can't set cmd.Dir to an absolute path that includes rootfs here
		// because Chroot is applied in the child — the child sees the path relative to rootfs.
		// So we set Dir to the workdir as it will appear inside the container.
		cmd.Dir = workdir
	} else {
		cmd.Dir = "/"
	}

	if err := cmd.Run(); err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return exitErr.ExitCode(), nil
		}
		return -1, err
	}
	return 0, nil
}

// RunImage assembles layers, isolates, and runs the container.
func RunImage(manifest *models.ImageManifest, commandOverride []string, envOverrides map[string]string) (int, error) {
	command := commandOverride
	if len(command) == 0 {
		command = manifest.Config.Cmd
	}
	if len(command) == 0 {
		return -1, fmt.Errorf("[RUNTIME ERROR] No command provided and image has no CMD")
	}

	imageEnv := parseEnvList(manifest.Config.Env)
	mergedEnv := make(map[string]string)
	for k, v := range imageEnv {
		mergedEnv[k] = v
	}
	for k, v := range envOverrides {
		mergedEnv[k] = v
	}
	workdir := manifest.Config.WorkingDir
	if workdir == "" {
		workdir = "/"
	}

	rootfs, err := os.MkdirTemp("", "docksmith_run_")
	if err != nil {
		return -1, err
	}
	defer os.RemoveAll(rootfs)

	for _, layer := range manifest.Layers {
		if err := layers.ExtractLayer(layer.Digest, rootfs); err != nil {
			return -1, err
		}
	}

	code, err := IsolateAndRun(rootfs, command, mergedEnv, workdir)
	if err != nil {
		return -1, err
	}
	return code, nil
}

func parseEnvList(items []string) map[string]string {
	env := make(map[string]string)
	for _, item := range items {
		if idx := strings.Index(item, "="); idx >= 0 {
			env[item[:idx]] = item[idx+1:]
		}
	}
	return env
}
