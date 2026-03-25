package paths

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
)

var (
	once     sync.Once
	stateDir string
)

// StateRoot returns the resolved ~/.docksmith directory (or DOCKSMITH_HOME override).
func StateRoot() (string, error) {
	var err error
	once.Do(func() {
		candidates := []string{}
		if env := os.Getenv("DOCKSMITH_HOME"); env != "" {
			candidates = append(candidates, env)
		}
		home, herr := os.UserHomeDir()
		if herr == nil {
			candidates = append(candidates, filepath.Join(home, ".docksmith"))
		}
		cwd, _ := os.Getwd()
		candidates = append(candidates, filepath.Join(cwd, ".docksmith"))

		for _, c := range candidates {
			if merr := os.MkdirAll(c, 0755); merr == nil {
				stateDir = c
				return
			}
		}
		err = fmt.Errorf("[STATE ERROR] unable to create docksmith state directory")
	})
	if err != nil {
		return "", err
	}
	return stateDir, nil
}

func ImagesDir() (string, error) {
	root, err := StateRoot()
	if err != nil {
		return "", err
	}
	return filepath.Join(root, "images"), nil
}

func LayersDir() (string, error) {
	root, err := StateRoot()
	if err != nil {
		return "", err
	}
	return filepath.Join(root, "layers"), nil
}

func CacheDir() (string, error) {
	root, err := StateRoot()
	if err != nil {
		return "", err
	}
	return filepath.Join(root, "cache"), nil
}

// EnsureStateDirs creates all three subdirectories.
func EnsureStateDirs() error {
	for _, fn := range []func() (string, error){ImagesDir, LayersDir, CacheDir} {
		d, err := fn()
		if err != nil {
			return err
		}
		if err := os.MkdirAll(d, 0755); err != nil {
			return err
		}
	}
	return nil
}
