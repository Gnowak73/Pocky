package utils

import (
	"os"
	"path/filepath"
)

// AtomicSave writes data to a temp file in the same dir and renames it into place.
func AtomicSave(target string, tmpPrefix string, data []byte, perm os.FileMode) error {
	dir := filepath.Dir(target)
	tmp, err := os.CreateTemp(dir, tmpPrefix)
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	defer func() {
		_ = os.Remove(tmpPath)
	}()
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.WriteFile(tmpPath, data, perm); err != nil {
		return err
	}
	return os.Rename(tmpPath, target)
}
