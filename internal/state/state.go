package state

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"docksmith/internal/layers"
	"docksmith/internal/models"
	"docksmith/internal/paths"
)

func manifestFilename(name, tag string) string {
	return name + ":" + tag + ".json"
}

func manifestPath(name, tag string) (string, error) {
	imagesDir, err := paths.ImagesDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(imagesDir, manifestFilename(name, tag)), nil
}

// computeManifestDigest hashes the manifest with digest="" to produce the canonical digest.
func computeManifestDigest(m models.ImageManifest) string {
	m.Digest = ""
	data, _ := json.Marshal(m)

	// Re-marshal with sort_keys equivalent: use a sorted map approach
	var raw map[string]interface{}
	json.Unmarshal(data, &raw)
	canonical, _ := json.Marshal(raw)

	h := sha256.Sum256(canonical)
	return fmt.Sprintf("sha256:%x", h)
}

// SaveManifest writes a manifest to disk, computing the digest first.
func SaveManifest(m models.ImageManifest) (models.ImageManifest, error) {
	if err := paths.EnsureStateDirs(); err != nil {
		return models.ImageManifest{}, err
	}

	m.Digest = computeManifestDigest(m)

	p, err := manifestPath(m.Name, m.Tag)
	if err != nil {
		return models.ImageManifest{}, err
	}

	data, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return models.ImageManifest{}, err
	}
	if err := os.WriteFile(p, data, 0644); err != nil {
		return models.ImageManifest{}, err
	}
	return m, nil
}

// LoadManifest reads a manifest from disk. Returns nil, nil if not found.
func LoadManifest(name, tag string) (*models.ImageManifest, error) {
	if err := paths.EnsureStateDirs(); err != nil {
		return nil, err
	}
	p, err := manifestPath(name, tag)
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(p)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var m models.ImageManifest
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, err
	}
	return &m, nil
}

// ListManifests returns all manifests in the images directory.
func ListManifests() ([]models.ImageManifest, error) {
	if err := paths.EnsureStateDirs(); err != nil {
		return nil, err
	}
	imagesDir, err := paths.ImagesDir()
	if err != nil {
		return nil, err
	}
	entries, err := os.ReadDir(imagesDir)
	if err != nil {
		return nil, err
	}

	var names []string
	for _, e := range entries {
		if filepath.Ext(e.Name()) == ".json" {
			names = append(names, e.Name())
		}
	}
	sort.Strings(names)

	var manifests []models.ImageManifest
	for _, fname := range names {
		data, err := os.ReadFile(filepath.Join(imagesDir, fname))
		if err != nil {
			continue
		}
		var m models.ImageManifest
		if err := json.Unmarshal(data, &m); err != nil {
			continue
		}
		manifests = append(manifests, m)
	}
	return manifests, nil
}

// RemoveImage deletes the manifest and all its layer files.
func RemoveImage(name, tag string) (bool, error) {
	m, err := LoadManifest(name, tag)
	if err != nil {
		return false, err
	}
	if m == nil {
		return false, nil
	}
	for _, layer := range m.Layers {
		layers.DeleteLayer(layer.Digest)
	}
	p, err := manifestPath(name, tag)
	if err != nil {
		return false, err
	}
	if err := os.Remove(p); err != nil && !os.IsNotExist(err) {
		return false, err
	}
	return true, nil
}
