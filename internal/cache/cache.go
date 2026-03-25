package cache

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"docksmith/internal/layers"
	"docksmith/internal/paths"
)

// ComputeCacheKey hashes all inputs deterministically into a hex string.
func ComputeCacheKey(prevDigest, instructionText, workdir, envSerialized string, copyHashes []string) string {
	sorted := append([]string(nil), copyHashes...)
	sort.Strings(sorted)

	payload := map[string]interface{}{
		"prev_digest":      prevDigest,
		"instruction_text": instructionText,
		"workdir":          workdir,
		"env":              envSerialized,
		"copy_hashes":      sorted,
	}
	raw, _ := json.Marshal(payload)
	h := sha256.Sum256(raw)
	return fmt.Sprintf("%x", h)
}

// Manager handles cache lookup and storage.
type Manager struct {
	noCache bool
}

// NewManager creates a cache manager. If noCache is true, all lookups return miss.
func NewManager(noCache bool) *Manager {
	paths.EnsureStateDirs()
	return &Manager{noCache: noCache}
}

func (m *Manager) keyPath(key string) (string, error) {
	cacheDir, err := paths.CacheDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(cacheDir, key), nil
}

// Lookup returns the stored layer digest for a cache hit, or "" for a miss.
func (m *Manager) Lookup(prevDigest, instructionText, workdir, envSerialized string, copyHashes []string) string {
	if m.noCache {
		return ""
	}
	key := ComputeCacheKey(prevDigest, instructionText, workdir, envSerialized, copyHashes)
	p, err := m.keyPath(key)
	if err != nil {
		return ""
	}
	data, err := os.ReadFile(p)
	if err != nil {
		return ""
	}
	digest := strings.TrimSpace(string(data))
	if digest == "" || !layers.LayerExists(digest) {
		return ""
	}
	return digest
}

// Store writes a cache key → layer digest mapping to disk.
func (m *Manager) Store(prevDigest, instructionText, workdir, envSerialized string, copyHashes []string, resultDigest string) {
	if m.noCache {
		return
	}
	key := ComputeCacheKey(prevDigest, instructionText, workdir, envSerialized, copyHashes)
	p, err := m.keyPath(key)
	if err != nil {
		return
	}
	os.WriteFile(p, []byte(resultDigest), 0644)
}

// SerializeEnv converts env map to "A=1&B=2" sorted string for cache key input.
func SerializeEnv(env map[string]string) string {
	if len(env) == 0 {
		return ""
	}
	keys := make([]string, 0, len(env))
	for k := range env {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var parts []string
	for _, k := range keys {
		parts = append(parts, k+"="+env[k])
	}
	return strings.Join(parts, "&")
}
