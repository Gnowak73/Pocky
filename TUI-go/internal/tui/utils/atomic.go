package utils

import (
	"os"
	"path/filepath"
)

// AtomicSave writes data to a temp file in the same dir and renames it into place.
func AtomicSave(target string, tmpPrefix string, data []byte, perm os.FileMode) error {
	// tmpPrefix is the filename pattern passed with a * at the end
	// target is the exact file directory of the file you want to save or replace.

	// We will first make a temp file and find the full disk path. Then, while the
	// file handle is open, we write the data to it. Writes are typically buffered in memory
	// first, in a chache, but it depends on the filesystem and OS. To ensure on
	// crash it works, we Sync the temp file to be in stable storage (disk) then close and
	// give permissions.
	dir := filepath.Dir(target)
	tmp, err := os.CreateTemp(dir, tmpPrefix)
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	defer func() {
		_ = os.Remove(tmpPath)
	}()
	if _, err := tmp.Write(data); err != nil {
		return err
	}
	if err := tmp.Sync(); err != nil {
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Chmod(tmpPath, perm); err != nil {
		return err
	}
	return os.Rename(tmpPath, target)
}
