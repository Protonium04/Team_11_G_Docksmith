package layers

import (
	"archive/tar"
	"bytes"
	"crypto/sha256"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"docksmith/internal/paths"
)

// SHA256OfBytes returns "sha256:<hexdigest>" for the given bytes.
func SHA256OfBytes(data []byte) string {
	h := sha256.Sum256(data)
	return fmt.Sprintf("sha256:%x", h)
}

// SHA256OfFile returns the hex digest (no prefix) of a file's contents.
func SHA256OfFile(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return fmt.Sprintf("%x", h.Sum(nil)), nil
}

// CollectAllPaths returns all file and directory paths under dir, sorted lexicographically.
func CollectAllPaths(dir string) ([]string, error) {
	var paths []string
	err := filepath.Walk(dir, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if p == dir {
			return nil
		}
		paths = append(paths, p)
		return nil
	})
	sort.Strings(paths)
	return paths, err
}

// CreateDeltaTar creates a reproducible tar archive (zeroed timestamps, sorted entries).
// Returns raw tar bytes.
func CreateDeltaTar(baseDir string, absPaths []string) ([]byte, error) {
	// Deduplicate and sort
	seen := make(map[string]bool)
	var unique []string
	for _, p := range absPaths {
		if !seen[p] {
			seen[p] = true
			unique = append(unique, p)
		}
	}
	sort.Strings(unique)

	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)

	for _, absPath := range unique {
		info, err := os.Lstat(absPath)
		if err != nil {
			continue // skip if gone
		}
		relPath, err := filepath.Rel(baseDir, absPath)
		if err != nil {
			return nil, err
		}
		// Normalise to forward slashes
		relPath = filepath.ToSlash(relPath)

		hdr := &tar.Header{
			Name:     relPath,
			Mode:     int64(info.Mode()),
			ModTime:  time.Time{},
			Uid:      0,
			Gid:      0,
			Uname:    "",
			Gname:    "",
			Typeflag: tar.TypeReg,
		}

		if info.IsDir() {
			hdr.Typeflag = tar.TypeDir
			hdr.Name = relPath + "/"
			if err := tw.WriteHeader(hdr); err != nil {
				return nil, err
			}
			continue
		}

		if info.Mode()&os.ModeSymlink != 0 {
			target, err := os.Readlink(absPath)
			if err != nil {
				return nil, err
			}
			hdr.Typeflag = tar.TypeSymlink
			hdr.Linkname = target
			hdr.Size = 0
			if err := tw.WriteHeader(hdr); err != nil {
				return nil, err
			}
			continue
		}

		hdr.Size = info.Size()
		if err := tw.WriteHeader(hdr); err != nil {
			return nil, err
		}
		f, err := os.Open(absPath)
		if err != nil {
			return nil, err
		}
		if _, err := io.Copy(tw, f); err != nil {
			f.Close()
			return nil, err
		}
		f.Close()
	}

	if err := tw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// StoreLayer writes tar bytes to ~/.docksmith/layers/<hexhash>.
// Returns "sha256:<hexhash>". Skips write if already present.
func StoreLayer(tarBytes []byte) (string, error) {
	if err := paths.EnsureStateDirs(); err != nil {
		return "", err
	}
	layersDir, err := paths.LayersDir()
	if err != nil {
		return "", err
	}

	digest := SHA256OfBytes(tarBytes)
	hexHash := strings.TrimPrefix(digest, "sha256:")
	layerPath := filepath.Join(layersDir, hexHash)

	if _, err := os.Stat(layerPath); err == nil {
		return digest, nil // already exists
	}

	tmpPath := layerPath + ".tmp"
	if err := os.WriteFile(tmpPath, tarBytes, 0644); err != nil {
		return "", err
	}
	if err := os.Rename(tmpPath, layerPath); err != nil {
		os.Remove(tmpPath)
		return "", err
	}
	return digest, nil
}

// LayerExists reports whether a layer file is on disk.
func LayerExists(digest string) bool {
	layersDir, err := paths.LayersDir()
	if err != nil {
		return false
	}
	hexHash := strings.TrimPrefix(digest, "sha256:")
	_, err = os.Stat(filepath.Join(layersDir, hexHash))
	return err == nil
}

// GetLayerSize returns the byte size of a stored layer.
func GetLayerSize(digest string) (int64, error) {
	layersDir, err := paths.LayersDir()
	if err != nil {
		return 0, err
	}
	hexHash := strings.TrimPrefix(digest, "sha256:")
	info, err := os.Stat(filepath.Join(layersDir, hexHash))
	if err != nil {
		return 0, fmt.Errorf("[LAYER ERROR] layer not found: %s", digest)
	}
	return info.Size(), nil
}

// ExtractLayer extracts a stored layer tar into targetDir.
func ExtractLayer(digest, targetDir string) error {
	layersDir, err := paths.LayersDir()
	if err != nil {
		return err
	}
	hexHash := strings.TrimPrefix(digest, "sha256:")
	layerPath := filepath.Join(layersDir, hexHash)

	f, err := os.Open(layerPath)
	if err != nil {
		return fmt.Errorf("[RUNTIME ERROR] layer not found: %s — try rebuilding with --no-cache", digest)
	}
	defer f.Close()

	tr := tar.NewReader(f)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}

		target := filepath.Join(targetDir, filepath.FromSlash(hdr.Name))

		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, os.FileMode(hdr.Mode)|0755); err != nil {
				return err
			}
		case tar.TypeSymlink:
			os.Remove(target)
			if err := os.Symlink(hdr.Linkname, target); err != nil {
				return err
			}
		default:
			if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
				return err
			}
			out, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, os.FileMode(hdr.Mode))
			if err != nil {
				return err
			}
			if _, err := io.Copy(out, tr); err != nil {
				out.Close()
				return err
			}
			out.Close()
		}
	}
	return nil
}

// DeleteLayer removes a layer file from disk.
func DeleteLayer(digest string) error {
	layersDir, err := paths.LayersDir()
	if err != nil {
		return err
	}
	hexHash := strings.TrimPrefix(digest, "sha256:")
	path := filepath.Join(layersDir, hexHash)
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

// HashCopySources returns sorted "relpath:hexdigest" strings for files matched by srcPattern.
func HashCopySources(srcPattern, contextDir string) ([]string, error) {
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
			return nil, err
		}
	} else {
		pattern := filepath.Join(contextDir, srcPattern)
		m, err := filepath.Glob(pattern)
		if err != nil {
			return nil, err
		}
		matched = m
	}

	sort.Strings(matched)
	var result []string
	for _, absPath := range matched {
		info, err := os.Stat(absPath)
		if err != nil || info.IsDir() {
			continue
		}
		h, err := SHA256OfFile(absPath)
		if err != nil {
			return nil, err
		}
		rel, err := filepath.Rel(contextDir, absPath)
		if err != nil {
			return nil, err
		}
		result = append(result, filepath.ToSlash(rel)+":"+h)
	}
	sort.Strings(result)
	return result, nil
}

// SnapshotFilesystem returns a map of relpath → sha256hex for all files under dir.
func SnapshotFilesystem(dir string) (map[string]string, error) {
	snap := make(map[string]string)
	err := filepath.Walk(dir, func(p string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return nil
		}
		h, err := SHA256OfFile(p)
		if err != nil {
			return nil // skip unreadable files
		}
		rel, err := filepath.Rel(dir, p)
		if err != nil {
			return err
		}
		snap[filepath.ToSlash(rel)] = h
		return nil
	})
	return snap, err
}

// ComputeDeltaPaths returns absolute paths of files new or changed in after vs before.
func ComputeDeltaPaths(before, after map[string]string, baseDir string) []string {
	var changed []string
	for relPath, newHash := range after {
		if oldHash, ok := before[relPath]; !ok || oldHash != newHash {
			changed = append(changed, filepath.Join(baseDir, filepath.FromSlash(relPath)))
		}
	}
	sort.Strings(changed)
	return changed
}
