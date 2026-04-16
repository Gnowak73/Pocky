package main

import (
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

type miniforgeTarget struct {
	URL       string
	Installer string
}

func main() {
	root := mustWaffleRoot()
	envYML := filepath.Join(root, "waffle_env.yml")
	pipeline := filepath.Join(root, "near_realtime_aia_pipeline.py")

	if !fileExists(envYML) || !fileExists(pipeline) {
		fmt.Printf("Missing required files in %s\n", root)
		fmt.Println("Expected: waffle_env.yml and near_realtime_aia_pipeline.py")
		exitWithPause(1)
	}

	conda, err := findConda()
	if err != nil {
		fmt.Println("Conda not found. Installing Miniforge...")
		if err := installMiniforge(); err != nil {
			fmt.Printf("Auto-install failed: %v\n", err)
			fmt.Println("Install Miniforge manually, then rerun this launcher.")
			exitWithPause(1)
		}
		conda, err = findConda()
		if err != nil {
			fmt.Println("Miniforge installed, but conda is not yet on PATH.")
			fmt.Println("Restart terminal/session and run again.")
			exitWithPause(1)
		}
	}

	envName := "Waffle"
	if v := os.Getenv("WAFFLE_ENV_NAME"); strings.TrimSpace(v) != "" {
		envName = strings.TrimSpace(v)
	}

	if !envExists(conda, envName) {
		fmt.Printf("Creating conda env %q...\n", envName)
		if err := runCmd(conda, []string{"env", "create", "-n", envName, "-f", envYML}, root); err != nil {
			fmt.Printf("Failed to create env: %v\n", err)
			exitWithPause(1)
		}
	} else if os.Getenv("WAFFLE_FORCE_UPDATE") == "1" {
		fmt.Printf("Updating conda env %q...\n", envName)
		if err := runCmd(conda, []string{"env", "update", "-n", envName, "-f", envYML, "--prune"}, root); err != nil {
			fmt.Printf("Failed to update env: %v\n", err)
			exitWithPause(1)
		}
	} else {
		fmt.Printf("Conda env %q already exists.\n", envName)
	}

	fmt.Println("Starting WAFFLE...")
	if err := runCmd(conda, []string{"run", "--no-capture-output", "-n", envName, "python", pipeline}, root); err != nil {
		fmt.Printf("WAFFLE run failed: %v\n", err)
		exitWithPause(1)
	}
}

func mustWaffleRoot() string {
	exe, err := os.Executable()
	if err != nil {
		fmt.Println("Unable to resolve executable path.")
		exitWithPause(1)
	}
	// Hardcoded contract:
	// - Launcher runs from waffle_v1/launcher_go/dist
	// - WAFFLE root is ../../ from the executable.
	root := filepath.Clean(filepath.Join(filepath.Dir(exe), "..", ".."))
	if !fileExists(filepath.Join(root, "waffle_env.yml")) ||
		!fileExists(filepath.Join(root, "near_realtime_aia_pipeline.py")) {
		fmt.Println("Unable to find WAFFLE root from launcher location.")
		fmt.Printf("Expected at: %s\n", root)
		fmt.Println("Expected files:")
		fmt.Println(" - waffle_env.yml")
		fmt.Println(" - near_realtime_aia_pipeline.py")
		exitWithPause(1)
	}
	return root
}

func exitWithPause(code int) {
	if os.Getenv("WAFFLE_NO_PAUSE") != "1" {
		fmt.Println()
		fmt.Println("Launcher failed. Press Enter to close this window.")
		_, _ = fmt.Scanln()
	}
	os.Exit(code)
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func findConda() (string, error) {
	cands := []string{}
	if runtime.GOOS == "windows" {
		localAppData := os.Getenv("LOCALAPPDATA")
		userProfile := os.Getenv("USERPROFILE")
		cands = append(cands,
			filepath.Join(userProfile, "miniconda3", "condabin", "conda.bat"),
			filepath.Join(localAppData, "miniconda3", "condabin", "conda.bat"),
			`C:\ProgramData\miniconda3\condabin\conda.bat`,
			filepath.Join(userProfile, "miniforge3", "condabin", "conda.bat"),
			filepath.Join(localAppData, "miniforge3", "condabin", "conda.bat"),
			`C:\ProgramData\miniforge3\condabin\conda.bat`,
			filepath.Join(localAppData, "anaconda3", "condabin", "conda.bat"),
			filepath.Join(userProfile, "anaconda3", "condabin", "conda.bat"),
			`C:\ProgramData\anaconda3\condabin\conda.bat`,
			"conda",
		)
	} else {
		cands = append(cands,
			filepath.Join(os.Getenv("HOME"), "miniconda3", "bin", "conda"),
			filepath.Join(os.Getenv("HOME"), "miniforge3", "bin", "conda"),
			filepath.Join(os.Getenv("HOME"), "anaconda3", "bin", "conda"),
			"conda",
		)
	}
	for _, c := range cands {
		if strings.TrimSpace(c) == "" {
			continue
		}
		if lp, err := exec.LookPath(c); err == nil {
			return lp, nil
		}
		if fileExists(c) {
			return c, nil
		}
	}
	return "", errors.New("conda not found")
}

func envExists(conda, envName string) bool {
	cmd := exec.Command(conda, "env", "list")
	out, err := cmd.Output()
	if err != nil {
		return false
	}
	for _, line := range strings.Split(string(out), "\n") {
		f := strings.Fields(line)
		if len(f) > 0 && f[0] == envName {
			return true
		}
	}
	return false
}

func runCmd(bin string, args []string, dir string) error {
	cmd := exec.Command(bin, args...)
	cmd.Dir = dir
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	return cmd.Run()
}

func installMiniforge() error {
	t, err := getMiniforgeTarget()
	if err != nil {
		return err
	}
	tmpDir, err := os.MkdirTemp("", "waffle-miniforge-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(tmpDir)

	installerPath := filepath.Join(tmpDir, t.Installer)
	if err := downloadFile(installerPath, t.URL); err != nil {
		return err
	}

	switch runtime.GOOS {
	case "darwin", "linux":
		target := filepath.Join(os.Getenv("HOME"), "miniforge3")
		if err := runCmd("bash", []string{installerPath, "-b", "-p", target}, tmpDir); err != nil {
			return err
		}
	case "windows":
		target := filepath.Join(os.Getenv("USERPROFILE"), "miniforge3")
		args := []string{"/InstallationType=JustMe", "/RegisterPython=0", "/S", "/D=" + target}
		if err := runCmd(installerPath, args, tmpDir); err != nil {
			return err
		}
	default:
		return fmt.Errorf("unsupported OS: %s", runtime.GOOS)
	}
	return nil
}

func getMiniforgeTarget() (miniforgeTarget, error) {
	base := "https://github.com/conda-forge/miniforge/releases/latest/download/"
	arch := runtime.GOARCH
	switch arch {
	case "amd64":
		arch = "x86_64"
	case "arm64":
		arch = "arm64"
	default:
		return miniforgeTarget{}, fmt.Errorf("unsupported architecture: %s", runtime.GOARCH)
	}

	switch runtime.GOOS {
	case "darwin":
		name := fmt.Sprintf("Miniforge3-MacOSX-%s.sh", arch)
		return miniforgeTarget{URL: base + name, Installer: name}, nil
	case "linux":
		name := fmt.Sprintf("Miniforge3-Linux-%s.sh", arch)
		return miniforgeTarget{URL: base + name, Installer: name}, nil
	case "windows":
		if arch != "x86_64" {
			return miniforgeTarget{}, fmt.Errorf("windows installer currently supported for x86_64 only")
		}
		name := "Miniforge3-Windows-x86_64.exe"
		return miniforgeTarget{URL: base + name, Installer: name}, nil
	default:
		return miniforgeTarget{}, fmt.Errorf("unsupported OS: %s", runtime.GOOS)
	}
}

func downloadFile(dst, url string) error {
	resp, err := http.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("download failed: %s", resp.Status)
	}
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, resp.Body)
	return err
}
