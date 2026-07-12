package packagex

import (
	"archive/zip"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"netconsole-agent/internal/util"
)

type Manifest struct {
	PackageType    string   `json:"package_type"`
	PackageVersion int      `json:"package_version"`
	TaskType       string   `json:"task_type"`
	TaskID         string   `json:"task_id"`
	AgentID        string   `json:"agent_id"`
	AgentName      string   `json:"agent_name"`
	CreatedAt      string   `json:"created_at"`
	StartTime      string   `json:"start_time"`
	EndTime        string   `json:"end_time"`
	Status         string   `json:"status"`
	RawFiles       []string `json:"raw_files"`
}

type TaskView struct {
	ID        string `json:"task_id"`
	Type      string `json:"task_type"`
	Status    string `json:"status"`
	StartTime string `json:"start_time"`
	EndTime   string `json:"end_time"`
}

type Packager struct {
	Dir       string
	AgentID   string
	AgentName string
	Version   string
}

type Info struct {
	ID          string `json:"package_id"`
	TaskID      string `json:"task_id"`
	TaskType    string `json:"task_type"`
	StartTime   string `json:"start_time"`
	EndTime     string `json:"end_time"`
	Size        int64  `json:"size"`
	DownloadURL string `json:"package_download_url"`
}

func (p *Packager) Create(taskDir string, task TaskView) (Info, error) {
	if err := os.MkdirAll(p.Dir, 0o755); err != nil {
		return Info{}, err
	}
	rawFiles, err := listRaw(taskDir)
	if err != nil {
		return Info{}, err
	}
	manifest := Manifest{
		PackageType: "netconsole_agent_collect_package", PackageVersion: 1,
		TaskType: task.Type, TaskID: task.ID, AgentID: p.AgentID, AgentName: p.AgentName,
		CreatedAt: time.Now().Format(time.RFC3339Nano), StartTime: task.StartTime,
		EndTime: task.EndTime, Status: task.Status, RawFiles: rawFiles,
	}
	generated := filepath.Join(taskDir, "meta", "package")
	if err := os.MkdirAll(generated, 0o755); err != nil {
		return Info{}, err
	}
	if err := util.WriteJSONAtomic(filepath.Join(generated, "manifest.json"), manifest, 0o600); err != nil {
		return Info{}, err
	}
	if err := util.WriteJSONAtomic(filepath.Join(generated, "agent_info.json"), map[string]any{
		"agent_id": p.AgentID, "agent_name": p.AgentName, "version": p.Version,
	}, 0o600); err != nil {
		return Info{}, err
	}
	if err := util.WriteJSONAtomic(filepath.Join(generated, "system_info.json"), map[string]any{
		"os": runtime.GOOS, "arch": runtime.GOARCH, "hostname": hostname(),
	}, 0o600); err != nil {
		return Info{}, err
	}

	finalPath := filepath.Join(p.Dir, task.ID+".zip")
	tmpPath := finalPath + ".tmp"
	_ = os.Remove(tmpPath)
	if err := writeZip(tmpPath, taskDir, generated, rawFiles); err != nil {
		_ = os.Remove(tmpPath)
		return Info{}, err
	}
	if err := util.ReplaceFile(tmpPath, finalPath); err != nil {
		_ = os.Remove(tmpPath)
		return Info{}, err
	}
	st, err := os.Stat(finalPath)
	if err != nil {
		return Info{}, err
	}
	return Info{ID: task.ID, TaskID: task.ID, TaskType: task.Type, StartTime: task.StartTime,
		EndTime: task.EndTime, Size: st.Size(), DownloadURL: "/api/v1/packages/" + task.ID + "/download"}, nil
}

func (p *Packager) List() ([]Info, error) {
	entries, err := os.ReadDir(p.Dir)
	if errorsIsNotExist(err) {
		return []Info{}, nil
	}
	if err != nil {
		return nil, err
	}
	out := make([]Info, 0)
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(strings.ToLower(entry.Name()), ".zip") {
			continue
		}
		path := filepath.Join(p.Dir, entry.Name())
		manifest, err := readManifest(path)
		if err != nil {
			continue
		}
		st, err := entry.Info()
		if err != nil {
			continue
		}
		id := strings.TrimSuffix(entry.Name(), filepath.Ext(entry.Name()))
		out = append(out, Info{ID: id, TaskID: manifest.TaskID, TaskType: manifest.TaskType,
			StartTime: manifest.StartTime, EndTime: manifest.EndTime, Size: st.Size(),
			DownloadURL: "/api/v1/packages/" + id + "/download"})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].EndTime > out[j].EndTime })
	return out, nil
}

func (p *Packager) Path(id string) (string, error) {
	if !safeID(id) {
		return "", fmt.Errorf("无效 package id")
	}
	path := filepath.Join(p.Dir, id+".zip")
	if _, err := os.Stat(path); err != nil {
		return "", err
	}
	return path, nil
}

func (p *Packager) Delete(id string) error {
	path, err := p.Path(id)
	if err != nil {
		return err
	}
	return os.Remove(path)
}

func writeZip(path, taskDir, generated string, rawFiles []string) error {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	zw := zip.NewWriter(f)
	add := func(source, name string) error {
		in, err := os.Open(source)
		if err != nil {
			return err
		}
		defer in.Close()
		w, err := zw.Create(filepath.ToSlash(name))
		if err != nil {
			return err
		}
		_, err = io.Copy(w, in)
		return err
	}
	files := [][2]string{
		{filepath.Join(generated, "manifest.json"), "manifest.json"},
		{filepath.Join(taskDir, "task.json"), "task.json"},
		{filepath.Join(generated, "agent_info.json"), "agent_info.json"},
		{filepath.Join(generated, "system_info.json"), "system_info.json"},
		{filepath.Join(taskDir, "stop_reason.json"), "stop_reason.json"},
		{filepath.Join(taskDir, "runtime.log"), "agent_runtime.log"},
	}
	if _, err := os.Stat(filepath.Join(taskDir, "target_snapshot.json")); err == nil {
		files = append(files, [2]string{filepath.Join(taskDir, "target_snapshot.json"), "target_snapshot.json"})
	}
	for _, item := range files {
		if err := add(item[0], item[1]); err != nil {
			_ = zw.Close()
			_ = f.Close()
			return err
		}
	}
	for _, rel := range rawFiles {
		if err := add(filepath.Join(taskDir, filepath.FromSlash(rel)), rel); err != nil {
			_ = zw.Close()
			_ = f.Close()
			return err
		}
	}
	if err := zw.Close(); err != nil {
		_ = f.Close()
		return err
	}
	return f.Close()
}

func listRaw(taskDir string) ([]string, error) {
	root := filepath.Join(taskDir, "raw")
	files := []string{}
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(taskDir, path)
		if err != nil {
			return err
		}
		files = append(files, filepath.ToSlash(rel))
		return nil
	})
	if errorsIsNotExist(err) {
		return files, nil
	}
	sort.Strings(files)
	return files, err
}

func readManifest(path string) (Manifest, error) {
	zr, err := zip.OpenReader(path)
	if err != nil {
		return Manifest{}, err
	}
	defer zr.Close()
	for _, f := range zr.File {
		if f.Name != "manifest.json" {
			continue
		}
		r, err := f.Open()
		if err != nil {
			return Manifest{}, err
		}
		defer r.Close()
		var m Manifest
		err = json.NewDecoder(r).Decode(&m)
		return m, err
	}
	return Manifest{}, fmt.Errorf("manifest.json 不存在")
}

func hostname() string { h, _ := os.Hostname(); return h }
func safeID(id string) bool {
	return id != "" && id != "." && id != ".." && !strings.ContainsAny(id, `/\\`)
}
func errorsIsNotExist(err error) bool { return err != nil && os.IsNotExist(err) }
