package builder

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"docksmith/internal/cache"
	"docksmith/internal/layers"
	"docksmith/internal/models"
	"docksmith/internal/parser"
	"docksmith/internal/runtime"
	"docksmith/internal/state"
)

// BuildImage is the main entry point for `docksmith build`.
func BuildImage(contextDir, name, tag string, noCache bool) (*models.ImageManifest, error) {
	docksmithfilePath := filepath.Join(contextDir, "Docksmithfile")
	instructions, err := parser.ParseDocksmithfile(docksmithfilePath)
	if err != nil {
		return nil, err
	}

	totalSteps := len(instructions)
	var layerEntries []models.LayerEntry
	envDict := make(map[string]string)
	workdir := ""
	var cmd []string
	prevDigest := ""
	cacheBusted := false
	buildStart := time.Now().UTC()
	var originalCreated string

	cm := cache.NewManager(noCache)

	fmt.Println()

	for stepIdx, instr := range instructions {
		label := fmt.Sprintf("Step %d/%d : %s %s", stepIdx+1, totalSteps, instr.Type, instr.Args)

		switch instr.Type {
		case "FROM":
			fmt.Println(label)
			baseName, baseTag := parser.ParseFromArgs(instr.Args)
			baseManifest, err := state.LoadManifest(baseName, baseTag)
			if err != nil {
				return nil, err
			}
			if baseManifest == nil {
				return nil, fmt.Errorf("[BUILD ERROR] FROM: image %q not found.\n  Run setup-base first to import base images.", instr.Args)
			}
			layerEntries = append([]models.LayerEntry(nil), baseManifest.Layers...)
			prevDigest = baseManifest.Digest
			for _, envStr := range baseManifest.Config.Env {
				if idx := strings.Index(envStr, "="); idx >= 0 {
					envDict[envStr[:idx]] = envStr[idx+1:]
				}
			}
			workdir = baseManifest.Config.WorkingDir
			cmd = baseManifest.Config.Cmd

			if existing, _ := state.LoadManifest(name, tag); existing != nil {
				originalCreated = existing.Created
			}

		case "WORKDIR":
			fmt.Println(label)
			workdir = instr.Args

		case "ENV":
			fmt.Println(label)
			k, v, err := parser.ParseEnvArgs(instr.Args)
			if err != nil {
				return nil, err
			}
			envDict[k] = v

		case "CMD":
			fmt.Println(label)
			cmd, err = parser.ParseCmdArgs(instr.Args)
			if err != nil {
				return nil, err
			}

		case "COPY":
			src, dest, err := parser.ParseCopyArgs(instr.Args)
			if err != nil {
				return nil, err
			}
			instructionText := "COPY " + instr.Args
			envSer := cache.SerializeEnv(envDict)
			copyHashes, err := layers.HashCopySources(src, contextDir)
			if err != nil {
				return nil, err
			}

			cachedDigest := ""
			if !cacheBusted {
				cachedDigest = cm.Lookup(prevDigest, instructionText, workdir, envSer, copyHashes)
			}

			if cachedDigest != "" {
				fmt.Printf("%s [CACHE HIT]\n", label)
				sz, _ := layers.GetLayerSize(cachedDigest)
				layerEntries = append(layerEntries, models.LayerEntry{
					Digest:    cachedDigest,
					Size:      sz,
					CreatedBy: instructionText,
				})
				prevDigest = cachedDigest
			} else {
				cacheBusted = true
				t0 := time.Now()
				digest, err := executeCopy(src, dest, contextDir, layerEntries, workdir)
				if err != nil {
					return nil, err
				}
				elapsed := time.Since(t0)
				fmt.Printf("%s [CACHE MISS] %.2fs\n", label, elapsed.Seconds())

				cm.Store(prevDigest, instructionText, workdir, envSer, copyHashes, digest)
				sz, _ := layers.GetLayerSize(digest)
				layerEntries = append(layerEntries, models.LayerEntry{
					Digest:    digest,
					Size:      sz,
					CreatedBy: instructionText,
				})
				prevDigest = digest
			}

		case "RUN":
			instructionText := "RUN " + instr.Args
			envSer := cache.SerializeEnv(envDict)

			cachedDigest := ""
			if !cacheBusted {
				cachedDigest = cm.Lookup(prevDigest, instructionText, workdir, envSer, nil)
			}

			if cachedDigest != "" {
				fmt.Printf("%s [CACHE HIT]\n", label)
				sz, _ := layers.GetLayerSize(cachedDigest)
				layerEntries = append(layerEntries, models.LayerEntry{
					Digest:    cachedDigest,
					Size:      sz,
					CreatedBy: instructionText,
				})
				prevDigest = cachedDigest
			} else {
				cacheBusted = true
				t0 := time.Now()
				digest, err := executeRun(instr.Args, layerEntries, envDict, workdir)
				if err != nil {
					return nil, err
				}
				elapsed := time.Since(t0)
				fmt.Printf("%s [CACHE MISS] %.2fs\n", label, elapsed.Seconds())

				cm.Store(prevDigest, instructionText, workdir, envSer, nil, digest)
				sz, _ := layers.GetLayerSize(digest)
				layerEntries = append(layerEntries, models.LayerEntry{
					Digest:    digest,
					Size:      sz,
					CreatedBy: instructionText,
				})
				prevDigest = digest
			}
		}
	}

	// Build env list
	envList := make([]string, 0, len(envDict))
	for k, v := range envDict {
		envList = append(envList, k+"="+v)
	}

	allHits := !cacheBusted
	created := buildStart.Format(time.RFC3339Nano)
	if allHits && originalCreated != "" {
		created = originalCreated
	}

	manifest := models.ImageManifest{
		Name:    name,
		Tag:     tag,
		Digest:  "",
		Created: created,
		Config: models.ImageConfig{
			Env:        envList,
			Cmd:        cmd,
			WorkingDir: workdir,
		},
		Layers: layerEntries,
	}

	saved, err := state.SaveManifest(manifest)
	if err != nil {
		return nil, err
	}

	totalTime := time.Since(buildStart)
	shortDigest := saved.Digest
	if len(shortDigest) > 19 {
		shortDigest = shortDigest[:19]
	}
	fmt.Printf("\nSuccessfully built %s %s:%s (%.2fs)\n\n", shortDigest, name, tag, totalTime.Seconds())
	return &saved, nil
}

func assembleRootfs(layerEntries []models.LayerEntry, targetDir string) error {
	for _, layer := range layerEntries {
		if err := layers.ExtractLayer(layer.Digest, targetDir); err != nil {
			return err
		}
	}
	return nil
}

func executeCopy(srcPattern, dest, contextDir string, currentLayers []models.LayerEntry, workdir string) (string, error) {
	rootfs, err := os.MkdirTemp("", "docksmith_copy_")
	if err != nil {
		return "", err
	}
	defer os.RemoveAll(rootfs)

	if err := assembleRootfs(currentLayers, rootfs); err != nil {
		return "", err
	}

	if workdir != "" {
		os.MkdirAll(filepath.Join(rootfs, strings.TrimPrefix(workdir, "/")), 0755)
	}

	destAbs := filepath.Join(rootfs, strings.TrimPrefix(dest, "/"))
	os.MkdirAll(destAbs, 0755)

	// Resolve source files
	var matched []string
	if srcPattern == "." {
		err := filepath.Walk(contextDir, func(p string, info os.FileInfo, err error) error {
			if err != nil {
				return err
			}
			if !info.IsDir() {
				matched = append(matched, p)
			}
			return nil
		})
		if err != nil {
			return "", err
		}
	} else {
		pattern := filepath.Join(contextDir, srcPattern)
		matched, err = filepath.Glob(pattern)
		if err != nil {
			return "", err
		}
	}

	if len(matched) == 0 {
		return "", fmt.Errorf("[COPY ERROR] no files matched %q in %q", srcPattern, contextDir)
	}

	for _, srcPath := range matched {
		info, err := os.Stat(srcPath)
		if err != nil {
			continue
		}
		rel, _ := filepath.Rel(contextDir, srcPath)
		if info.IsDir() {
			copyDir(srcPath, filepath.Join(destAbs, filepath.Base(srcPath)))
		} else {
			dstDir := filepath.Join(destAbs, filepath.Dir(rel))
			os.MkdirAll(dstDir, 0755)
			copyFile(srcPath, filepath.Join(dstDir, filepath.Base(srcPath)))
		}
	}

	allPaths, err := layers.CollectAllPaths(destAbs)
	if err != nil {
		return "", err
	}
	tarBytes, err := layers.CreateDeltaTar(rootfs, allPaths)
	if err != nil {
		return "", err
	}
	return layers.StoreLayer(tarBytes)
}

func executeRun(command string, currentLayers []models.LayerEntry, envDict map[string]string, workdir string) (string, error) {
	rootfs, err := os.MkdirTemp("", "docksmith_run_")
	if err != nil {
		return "", err
	}
	defer os.RemoveAll(rootfs)

	if err := assembleRootfs(currentLayers, rootfs); err != nil {
		return "", err
	}

	effectiveWorkdir := workdir
	if effectiveWorkdir == "" {
		effectiveWorkdir = "/"
	}
	os.MkdirAll(filepath.Join(rootfs, strings.TrimPrefix(effectiveWorkdir, "/")), 0755)

	before, err := layers.SnapshotFilesystem(rootfs)
	if err != nil {
		return "", err
	}

	exitCode, err := runtime.IsolateAndRun(rootfs, []string{"/bin/sh", "-c", command}, envDict, effectiveWorkdir)
	if err != nil {
		return "", err
	}
	if exitCode != 0 {
		return "", fmt.Errorf("[BUILD ERROR] RUN failed (exit %d):\n  %s", exitCode, command)
	}

	after, err := layers.SnapshotFilesystem(rootfs)
	if err != nil {
		return "", err
	}

	changedPaths := layers.ComputeDeltaPaths(before, after, rootfs)
	tarBytes, err := layers.CreateDeltaTar(rootfs, changedPaths)
	if err != nil {
		return "", err
	}
	return layers.StoreLayer(tarBytes)
}

func copyFile(src, dst string) error {
	data, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	info, err := os.Stat(src)
	if err != nil {
		return err
	}
	return os.WriteFile(dst, data, info.Mode())
}

func copyDir(src, dst string) error {
	return filepath.Walk(src, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(src, p)
		target := filepath.Join(dst, rel)
		if info.IsDir() {
			return os.MkdirAll(target, info.Mode())
		}
		return copyFile(p, target)
	})
}
