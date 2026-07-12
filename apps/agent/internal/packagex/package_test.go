package packagex

import (
	"archive/zip"
	"os"
	"path/filepath"
	"testing"
)

func TestCreateCanAtomicallyReplaceExistingPackage(t *testing.T) {
	root := t.TempDir()
	taskDir := filepath.Join(root, "task")
	for _, dir := range []string{filepath.Join(taskDir, "raw"), filepath.Join(taskDir, "meta")} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	files := map[string]string{"task.json": "{}\n", "stop_reason.json": "{}\n", "runtime.log": "ok\n", filepath.Join("raw", "sample.log"): "raw\n"}
	for name, content := range files {
		if err := os.WriteFile(filepath.Join(taskDir, name), []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	p := &Packager{Dir: filepath.Join(root, "packages"), AgentID: "a1", AgentName: "Agent", Version: "test"}
	task := TaskView{ID: "task-1", Type: "ping_probe", Status: "completed", StartTime: "2026-01-01T00:00:00Z", EndTime: "2026-01-01T00:01:00Z"}
	if _, err := p.Create(taskDir, task); err != nil {
		t.Fatal(err)
	}
	if _, err := p.Create(taskDir, task); err != nil {
		t.Fatalf("replace package: %v", err)
	}
	path, err := p.Path(task.ID)
	if err != nil {
		t.Fatal(err)
	}
	zr, err := zip.OpenReader(path)
	if err != nil {
		t.Fatal(err)
	}
	defer zr.Close()
	found := false
	for _, file := range zr.File {
		if file.Name == "raw/sample.log" {
			found = true
		}
	}
	if !found {
		t.Fatal("raw file missing")
	}
}
