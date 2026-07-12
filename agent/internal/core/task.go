package core

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"netconsole-agent/internal/packagex"
	"netconsole-agent/internal/util"
)

type Status string

const (
	Created               Status = "created"
	Running               Status = "running"
	Stopping              Status = "stopping"
	Completed             Status = "completed"
	Stopped               Status = "stopped"
	CompletedWithWarnings Status = "completed_with_warnings"
	StoppedWithWarnings   Status = "stopped_with_warnings"
	Failed                Status = "failed"
	Cancelled             Status = "cancelled"
)

type Task struct {
	TaskID             string          `json:"task_id"`
	TaskType           string          `json:"task_type"`
	Status             Status          `json:"status"`
	CreatedAt          string          `json:"created_at"`
	StartTime          string          `json:"start_time"`
	EndTime            string          `json:"end_time"`
	PackageID          string          `json:"package_id"`
	PackageDownloadURL string          `json:"package_download_url"`
	ErrorCode          string          `json:"error_code,omitempty"`
	ErrorMessage       string          `json:"error_message"`
	Params             json.RawMessage `json:"params,omitempty"`
}

type Runtime struct {
	TaskID string
	Dir    string
	RawDir string
	Ctx    context.Context
	logMu  sync.Mutex
	events *eventStore
}

func (r *Runtime) Log(format string, args ...any) {
	r.logMu.Lock()
	defer r.logMu.Unlock()
	f, err := os.OpenFile(filepath.Join(r.Dir, "runtime.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return
	}
	defer f.Close()
	_, _ = fmt.Fprintf(f, "%s %s\n", time.Now().Format(time.RFC3339Nano), fmt.Sprintf(format, args...))
}

func (r *Runtime) Emit(eventType, source string, payload map[string]any) (Event, error) {
	if r.events == nil {
		r.events = newEventStore(r.Dir)
	}
	return r.events.append(eventType, source, payload)
}

func (r *Runtime) WriteResult(summary map[string]any, artifacts []Artifact) error {
	return writeResult(r.Dir, summary, artifacts)
}

type Runner func(*Runtime) error

type runningTask struct {
	task        *Task
	cancel      context.CancelFunc
	done        chan struct{}
	dir         string
	events      *eventStore
	autoPackage bool
}

type Manager struct {
	mu          sync.RWMutex
	root        string
	tasks       map[string]*Task
	running     map[string]*runningTask
	activeTypes map[string]string
	packager    *packagex.Packager
	autoPackage bool
}

func NewManager(dataDir string, packager *packagex.Packager, autoPackage bool) (*Manager, error) {
	root := filepath.Join(dataDir, "tasks")
	if err := os.MkdirAll(root, 0o755); err != nil {
		return nil, err
	}
	m := &Manager{root: root, tasks: map[string]*Task{}, running: map[string]*runningTask{}, activeTypes: map[string]string{}, packager: packager, autoPackage: autoPackage}
	entries, _ := os.ReadDir(root)
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		b, err := os.ReadFile(filepath.Join(root, entry.Name(), "task.json"))
		if err != nil {
			continue
		}
		var task Task
		if json.Unmarshal(b, &task) == nil {
			if task.Status == Running || task.Status == Stopping || task.Status == Created {
				task.Status = Failed
				task.EndTime = time.Now().Format(time.RFC3339Nano)
				task.ErrorMessage = "Agent 重启，原运行任务已中断"
				_ = util.WriteJSONAtomic(filepath.Join(root, entry.Name(), "task.json"), task, 0o600)
				store := newEventStore(filepath.Join(root, entry.Name()))
				_, _ = store.append("system", "task", map[string]any{"message": task.ErrorMessage})
				_, _ = store.append("state", "task", map[string]any{"status": Failed})
			}
			m.tasks[task.TaskID] = &task
		}
	}
	return m, nil
}

func (m *Manager) Start(taskType string, params any, targetSnapshot any, runner Runner) (Task, error) {
	return m.start(taskType, params, targetSnapshot, m.autoPackage, runner)
}

func (m *Manager) StartWithPackage(taskType string, params any, targetSnapshot any, autoPackage bool, runner Runner) (Task, error) {
	return m.start(taskType, params, targetSnapshot, autoPackage, runner)
}

func (m *Manager) start(taskType string, params any, targetSnapshot any, autoPackage bool, runner Runner) (Task, error) {
	m.mu.Lock()
	if id := m.activeTypes[taskType]; id != "" {
		t := *m.tasks[id]
		m.mu.Unlock()
		return t, fmt.Errorf("同类任务已在运行: %s", id)
	}
	now := time.Now()
	id := fmt.Sprintf("%s_%s_%06d", now.Format("20060102_150405"), shortType(taskType), now.UnixNano()%1000000)
	dir := filepath.Join(m.root, id)
	if err := os.MkdirAll(filepath.Join(dir, "raw"), 0o755); err != nil {
		m.mu.Unlock()
		return Task{}, err
	}
	if err := os.MkdirAll(filepath.Join(dir, "meta"), 0o755); err != nil {
		m.mu.Unlock()
		return Task{}, err
	}
	paramJSON, err := json.Marshal(params)
	if err != nil {
		m.mu.Unlock()
		return Task{}, err
	}
	task := &Task{TaskID: id, TaskType: taskType, Status: Running, CreatedAt: now.Format(time.RFC3339Nano), StartTime: now.Format(time.RFC3339Nano), Params: paramJSON}
	ctx, cancel := context.WithCancel(context.Background())
	rt := &runningTask{task: task, cancel: cancel, done: make(chan struct{}), dir: dir, events: newEventStore(dir), autoPackage: autoPackage}
	m.tasks[id] = task
	m.running[id] = rt
	m.activeTypes[taskType] = id
	if err := util.WriteJSONAtomic(filepath.Join(dir, "task.json"), task, 0o600); err != nil {
		delete(m.tasks, id)
		delete(m.running, id)
		delete(m.activeTypes, taskType)
		cancel()
		m.mu.Unlock()
		return Task{}, err
	}
	if targetSnapshot != nil {
		if err := util.WriteJSONAtomic(filepath.Join(dir, "target_snapshot.json"), targetSnapshot, 0o600); err != nil {
			delete(m.tasks, id)
			delete(m.running, id)
			delete(m.activeTypes, taskType)
			cancel()
			m.mu.Unlock()
			return Task{}, err
		}
	}
	copyTask := *task
	m.mu.Unlock()
	go m.execute(rt, ctx, runner)
	return copyTask, nil
}

func (m *Manager) execute(rt *runningTask, ctx context.Context, runner Runner) {
	runtimeTask := &Runtime{TaskID: rt.task.TaskID, Dir: rt.dir, RawDir: filepath.Join(rt.dir, "raw"), Ctx: ctx, events: rt.events}
	runtimeTask.Log("任务启动 type=%s", rt.task.TaskType)
	_, _ = runtimeTask.Emit("state", "task", map[string]any{"status": Running, "task_type": rt.task.TaskType})
	runnerErr := runner(runtimeTask)
	m.mu.Lock()
	task := rt.task
	wasStopping := task.Status == Stopping
	task.EndTime = time.Now().Format(time.RFC3339Nano)
	finalStatus := Completed
	finalErrorCode := ""
	finalError := ""
	switch {
	case wasStopping || errors.Is(runnerErr, context.Canceled):
		finalStatus = Cancelled
	case runnerErr != nil && !errors.Is(runnerErr, context.Canceled):
		finalStatus = Failed
		finalError = runnerErr.Error()
		if coded, ok := runnerErr.(interface{ TrafficCode() string }); ok {
			finalErrorCode = coded.TrafficCode()
		}
	}
	if task.TaskType == "mr_realtime_collect" {
		if mrStatus, mrError := readMRStatus(rt.dir); mrStatus != "" {
			finalStatus = mrStatus
			if finalError == "" {
				finalError = mrError
			}
		} else if wasStopping || errors.Is(runnerErr, context.Canceled) {
			finalStatus = Stopped
		}
	}
	packageSnapshot := *task
	packageSnapshot.Status = finalStatus
	packageSnapshot.ErrorCode = finalErrorCode
	packageSnapshot.ErrorMessage = finalError
	m.mu.Unlock()
	if runnerErr != nil && !errors.Is(runnerErr, context.Canceled) {
		runtimeTask.Log("任务失败: %v", runnerErr)
		_, _ = runtimeTask.Emit("error", "task", map[string]any{"code": finalErrorCode, "message": runnerErr.Error()})
	} else {
		runtimeTask.Log("任务执行结束，准备提交 status=%s", finalStatus)
	}
	reason := map[string]any{"reason": "natural_completion", "stopped_at": packageSnapshot.EndTime}
	if wasStopping {
		reason["reason"] = "user_stop"
	}
	if finalStatus == Failed {
		reason["reason"] = "runner_error"
		reason["error"] = finalError
	}
	_ = util.WriteJSONAtomic(filepath.Join(rt.dir, "stop_reason.json"), reason, 0o600)
	_ = util.WriteJSONAtomic(filepath.Join(rt.dir, "task.json"), packageSnapshot, 0o600)
	var packageInfo packagex.Info
	if rt.autoPackage {
		info, packageErr := m.packager.Create(rt.dir, packagex.TaskView{ID: packageSnapshot.TaskID, Type: packageSnapshot.TaskType, Status: string(finalStatus), StartTime: packageSnapshot.StartTime, EndTime: packageSnapshot.EndTime})
		if packageErr != nil {
			finalStatus = Failed
			if finalError == "" {
				finalError = "自动打包失败: " + packageErr.Error()
			} else {
				finalError += "; 自动打包失败: " + packageErr.Error()
			}
		} else {
			packageInfo = info
		}
	}
	finalSnapshot := packageSnapshot
	finalSnapshot.Status = finalStatus
	finalSnapshot.ErrorCode = finalErrorCode
	finalSnapshot.ErrorMessage = finalError
	finalSnapshot.PackageID = packageInfo.ID
	finalSnapshot.PackageDownloadURL = packageInfo.DownloadURL
	_ = util.WriteJSONAtomic(filepath.Join(rt.dir, "task.json"), finalSnapshot, 0o600)
	runtimeTask.Log("任务提交完成 status=%s package_id=%s", finalSnapshot.Status, finalSnapshot.PackageID)
	_, _ = runtimeTask.Emit("state", "task", map[string]any{"status": finalSnapshot.Status, "error": finalSnapshot.ErrorMessage})
	m.mu.Lock()
	*task = finalSnapshot
	delete(m.running, task.TaskID)
	delete(m.activeTypes, task.TaskType)
	m.mu.Unlock()
	close(rt.done)
}

func readMRStatus(taskDir string) (Status, string) {
	b, err := os.ReadFile(filepath.Join(taskDir, "session_meta.json"))
	if err != nil {
		return "", ""
	}
	var meta map[string]any
	if json.Unmarshal(b, &meta) != nil {
		return "", ""
	}
	value, _ := meta["status"].(string)
	var status Status
	switch strings.ToUpper(strings.TrimSpace(value)) {
	case "STOPPED":
		status = Stopped
	case "STOPPED_WITH_WARNINGS":
		status = StoppedWithWarnings
	case "COMPLETED":
		status = Completed
	case "COMPLETED_WITH_WARNINGS":
		status = CompletedWithWarnings
	case "FAILED":
		status = Failed
	default:
		return "", ""
	}
	errorMessage, _ := meta["error_message"].(string)
	return status, errorMessage
}

func (m *Manager) Stop(id string) (Task, error) {
	m.mu.Lock()
	rt, ok := m.running[id]
	if !ok {
		if task, found := m.tasks[id]; found {
			copyTask := *task
			m.mu.Unlock()
			return copyTask, nil
		}
		m.mu.Unlock()
		return Task{}, fmt.Errorf("任务未运行或不存在: %s", id)
	}
	if rt.task.Status != Stopping {
		rt.task.Status = Stopping
		_ = util.WriteJSONAtomic(filepath.Join(rt.dir, "task.json"), rt.task, 0o600)
		_, _ = rt.events.append("state", "task", map[string]any{"status": Stopping})
		rt.cancel()
	}
	task := *rt.task
	m.mu.Unlock()
	return task, nil
}

func (m *Manager) StopType(taskType string) (Task, error) {
	m.mu.RLock()
	id := m.activeTypes[taskType]
	m.mu.RUnlock()
	if id == "" {
		return Task{}, fmt.Errorf("没有运行中的 %s 任务", taskType)
	}
	return m.Stop(id)
}

func (m *Manager) StopAll() []Task {
	m.mu.RLock()
	ids := make([]string, 0, len(m.running))
	for id := range m.running {
		ids = append(ids, id)
	}
	m.mu.RUnlock()
	stopped := make([]Task, 0, len(ids))
	for _, id := range ids {
		if task, err := m.Stop(id); err == nil {
			stopped = append(stopped, task)
		}
	}
	return stopped
}

func (m *Manager) WaitAll(timeout time.Duration) bool {
	m.mu.RLock()
	done := make([]<-chan struct{}, 0, len(m.running))
	for _, task := range m.running {
		done = append(done, task.done)
	}
	m.mu.RUnlock()
	deadline := time.NewTimer(timeout)
	defer deadline.Stop()
	for _, ch := range done {
		select {
		case <-ch:
		case <-deadline.C:
			return false
		}
	}
	return true
}

func (m *Manager) Get(id string) (Task, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	t, ok := m.tasks[id]
	if !ok {
		return Task{}, false
	}
	return *t, true
}

func (m *Manager) TaskDir(id string) (string, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if _, ok := m.tasks[id]; !ok {
		return "", false
	}
	return filepath.Join(m.root, id), true
}

func (m *Manager) Active(taskType string) (Task, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	id := m.activeTypes[taskType]
	if id == "" {
		return Task{}, false
	}
	return *m.tasks[id], true
}

func (m *Manager) List() []Task {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := make([]Task, 0, len(m.tasks))
	for _, t := range m.tasks {
		out = append(out, *t)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt > out[j].CreatedAt })
	return out
}

func (m *Manager) Counts() (current, total int) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return len(m.running), len(m.tasks)
}

func (m *Manager) Logs(id string, tail int) ([]string, error) {
	if tail <= 0 {
		tail = 200
	}
	if tail > 5000 {
		tail = 5000
	}
	path := filepath.Join(m.root, id, "runtime.log")
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	lines := []string{}
	scanner := bufio.NewScanner(f)
	buf := make([]byte, 64*1024)
	scanner.Buffer(buf, 1024*1024)
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
		if len(lines) > tail {
			lines = lines[len(lines)-tail:]
		}
	}
	return lines, scanner.Err()
}

func (m *Manager) Events(id string, after int64, limit int) (EventPage, error) {
	m.mu.RLock()
	_, exists := m.tasks[id]
	m.mu.RUnlock()
	if !exists {
		return EventPage{}, os.ErrNotExist
	}
	return readEventPage(id, filepath.Join(m.root, id, "events.jsonl"), after, limit)
}

func (m *Manager) Result(id string) (Result, error) {
	m.mu.RLock()
	task, exists := m.tasks[id]
	if !exists {
		m.mu.RUnlock()
		return Result{}, os.ErrNotExist
	}
	copyTask := *task
	m.mu.RUnlock()
	return readResult(copyTask, filepath.Join(m.root, id))
}

func shortType(taskType string) string {
	switch taskType {
	case "mr_realtime_collect":
		return "mr_collect"
	case "ping_probe":
		return "ping_probe"
	case "iperf_server":
		return "iperf_server"
	case "iperf_client":
		return "iperf_client"
	case "fping":
		return "fping"
	}
	return strings.ReplaceAll(taskType, " ", "_")
}
