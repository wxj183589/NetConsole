package api

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"netconsole-agent/internal/config"
	"netconsole-agent/internal/core"
	"netconsole-agent/internal/fping"
	"netconsole-agent/internal/iperf"
	"netconsole-agent/internal/mr"
	"netconsole-agent/internal/packagex"
	"netconsole-agent/internal/pingprobe"
	"netconsole-agent/internal/power"
	"netconsole-agent/internal/target"
	"netconsole-agent/internal/toolmanager"
	webassets "netconsole-agent/web"
)

type Server struct {
	cfg      *config.Config
	targets  *target.Store
	tasks    *core.Manager
	packages *packagex.Packager
	tools    *toolmanager.Manager
	power    *power.Manager
	started  time.Time
	version  string
}

func New(cfg *config.Config, targets *target.Store, tasks *core.Manager, packages *packagex.Packager, version string, powerManagers ...*power.Manager) *Server {
	powerManager := power.New()
	if len(powerManagers) > 0 && powerManagers[0] != nil {
		powerManager = powerManagers[0]
	}
	return &Server{cfg: cfg, targets: targets, tasks: tasks, packages: packages, tools: toolmanager.New(cfg), power: powerManager, started: time.Now(), version: version}
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.Handle("/api/v1/", s.auth(http.HandlerFunc(s.handleAPI)))
	mux.Handle("/", webassets.Handler())
	return recoverMiddleware(mux)
}

func (s *Server) handleAPI(w http.ResponseWriter, r *http.Request) {
	path := strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/"), "/")
	switch path {
	case "ping":
		s.requireMethod(w, r, http.MethodGet, func() { ok(w, map[string]any{"status": "ok", "time": time.Now().Format(time.RFC3339Nano)}) })
		return
	case "status":
		s.requireMethod(w, r, http.MethodGet, func() { s.status(w) })
		return
	case "capabilities":
		s.requireMethod(w, r, http.MethodGet, func() { s.capabilities(w, r) })
		return
	case "config":
		s.requireMethod(w, r, http.MethodGet, func() { s.config(w) })
		return
	case "tools/status":
		s.requireMethod(w, r, http.MethodGet, func() { ok(w, map[string]any{"tools": s.tools.Status(r.Context())}) })
		return
	case "power/status":
		s.requireMethod(w, r, http.MethodGet, func() { ok(w, map[string]any{"power": s.power.Status()}) })
		return
	case "power/prevent-sleep":
		s.requireMethod(w, r, http.MethodPost, func() { s.powerAction(w, func() error { return s.power.PreventSleep("api_request") }) })
		return
	case "power/prevent-sleep-display":
		s.requireMethod(w, r, http.MethodPost, func() { s.powerAction(w, func() error { return s.power.PreventSleepDisplay("api_request") }) })
		return
	case "power/restore":
		s.requireMethod(w, r, http.MethodPost, func() { s.powerAction(w, func() error { return s.power.Restore("api_request") }) })
		return
	case "targets":
		s.targetsRoot(w, r)
		return
	case "targets/import":
		s.targetsImport(w, r)
		return
	case "targets/export":
		s.targetsExport(w, r)
		return
	case "tasks":
		s.requireMethod(w, r, http.MethodGet, func() { ok(w, s.tasks.List()) })
		return
	case "iperf/server/start":
		s.iperfServerStart(w, r)
		return
	case "iperf/server/stop":
		s.stopType(w, r, "iperf_server")
		return
	case "iperf/server/status":
		s.typeStatus(w, r, "iperf_server")
		return
	case "iperf/client/start":
		s.iperfClientStart(w, r)
		return
	case "iperf/client/stop":
		s.stopType(w, r, "iperf_client")
		return
	case "iperf/client/status":
		s.typeStatus(w, r, "iperf_client")
		return
	case "ping-probe/start":
		s.pingStart(w, r)
		return
	case "ping-probe/stop":
		s.stopType(w, r, "ping_probe")
		return
	case "ping-probe/status":
		s.typeStatus(w, r, "ping_probe")
		return
	case "fping/start":
		s.fpingStart(w, r)
		return
	case "fping/stop":
		s.stopType(w, r, "fping")
		return
	case "fping/status":
		s.typeStatus(w, r, "fping")
		return
	case "mr/collect/start":
		s.mrStart(w, r)
		return
	case "mr/collect/stop":
		s.stopType(w, r, "mr_realtime_collect")
		return
	case "mr/collect/status":
		s.typeStatus(w, r, "mr_realtime_collect")
		return
	case "mr/collect/live":
		s.mrLive(w, r)
		return
	case "mr/collect/raw-tail":
		s.mrRawTail(w, r)
		return
	case "mr/collect/raw-summary":
		s.mrRawSummary(w, r)
		return
	case "packages":
		s.packagesRoot(w, r)
		return
	}
	parts := strings.Split(path, "/")
	if len(parts) >= 2 && parts[0] == "targets" {
		s.targetItem(w, r, parts)
		return
	}
	if len(parts) >= 2 && parts[0] == "tasks" {
		s.taskItem(w, r, parts)
		return
	}
	if len(parts) >= 2 && parts[0] == "packages" {
		s.packageItem(w, r, parts)
		return
	}
	fail(w, http.StatusNotFound, "接口不存在")
}

func (s *Server) status(w http.ResponseWriter) {
	current, total := s.tasks.Counts()
	packages, _ := s.packages.List()
	ok(w, map[string]any{"agent_id": s.cfg.Agent.ID, "agent_name": s.cfg.Agent.Name, "version": s.version, "os": runtime.GOOS, "arch": runtime.GOARCH, "listen": s.cfg.ListenAddress(), "uptime": time.Since(s.started).String(), "current_tasks": current, "task_count": total, "package_count": len(packages), "data_dir": s.cfg.DataPath(), "package_dir": s.cfg.PackagePath(), "power": s.power.Status(), "disk": map[string]any{}})
}

func (s *Server) capabilities(w http.ResponseWriter, r *http.Request) {
	tools := s.tools.Status(r.Context())
	ok(w, map[string]any{
		"iperf_server":         tools.Iperf3.Ready,
		"iperf_client":         tools.Iperf3.Ready,
		"fping":                tools.Fping.Ready,
		"ping_probe":           true,
		"tcp_ping_probe":       true,
		"task_events":          true,
		"task_result":          true,
		"online_mr_collection": true,
	})
}

func (s *Server) config(w http.ResponseWriter) {
	b, _ := json.Marshal(s.cfg)
	var value map[string]any
	_ = json.Unmarshal(b, &value)
	if sec, ok := value["security"].(map[string]any); ok {
		sec["token"] = "******"
		sec["web_password"] = "******"
	}
	ok(w, value)
}

func (s *Server) targetsRoot(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		ok(w, map[string]any{"targets": s.targets.List(true)})
	case http.MethodPost:
		var t target.Target
		if !decode(w, r, &t) {
			return
		}
		created, err := s.targets.Create(t)
		if err != nil {
			fail(w, 400, err.Error())
			return
		}
		ok(w, target.Sanitized(created))
	default:
		methodNotAllowed(w)
	}
}

func (s *Server) targetItem(w http.ResponseWriter, r *http.Request, parts []string) {
	id := parts[1]
	if len(parts) == 3 && parts[2] == "test" {
		if r.Method != http.MethodPost {
			methodNotAllowed(w)
			return
		}
		t, found := s.targets.Get(id)
		if !found {
			fail(w, 404, "目标不存在")
			return
		}
		if err := mr.TestConnection(t, 8*time.Second); err != nil {
			fail(w, 400, err.Error())
			return
		}
		ok(w, map[string]any{"target_id": id, "status": "ok"})
		return
	}
	switch r.Method {
	case http.MethodPut:
		var t target.Target
		if !decode(w, r, &t) {
			return
		}
		updated, err := s.targets.Update(id, t)
		if err != nil {
			fail(w, 400, err.Error())
			return
		}
		ok(w, target.Sanitized(updated))
	case http.MethodDelete:
		if err := s.targets.Delete(id); err != nil {
			fail(w, 404, err.Error())
			return
		}
		ok(w, map[string]any{"deleted": id})
	default:
		methodNotAllowed(w)
	}
}

func (s *Server) targetsImport(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		methodNotAllowed(w)
		return
	}
	var doc target.Document
	if !decode(w, r, &doc) {
		return
	}
	if err := s.targets.Import(doc); err != nil {
		fail(w, 400, err.Error())
		return
	}
	ok(w, map[string]any{"count": len(doc.Targets)})
}
func (s *Server) targetsExport(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	w.Header().Set("Content-Disposition", "attachment; filename=targets.json")
	writeJSON(w, 200, map[string]any{"targets": s.targets.List(true)})
}

func (s *Server) taskItem(w http.ResponseWriter, r *http.Request, parts []string) {
	id := parts[1]
	if len(parts) == 2 {
		if r.Method != http.MethodGet {
			methodNotAllowed(w)
			return
		}
		t, found := s.tasks.Get(id)
		if !found {
			fail(w, 404, "任务不存在")
			return
		}
		ok(w, t)
		return
	}
	if len(parts) == 3 && parts[2] == "stop" {
		if r.Method != http.MethodPost {
			methodNotAllowed(w)
			return
		}
		t, err := s.tasks.Stop(id)
		if err != nil {
			fail(w, 400, err.Error())
			return
		}
		ok(w, t)
		return
	}
	if len(parts) == 3 && parts[2] == "logs" {
		if r.Method != http.MethodGet {
			methodNotAllowed(w)
			return
		}
		tail, _ := strconv.Atoi(r.URL.Query().Get("tail"))
		lines, err := s.tasks.Logs(id, tail)
		if err != nil {
			fail(w, 404, err.Error())
			return
		}
		ok(w, map[string]any{"task_id": id, "lines": lines})
		return
	}
	if len(parts) == 3 && parts[2] == "events" {
		if r.Method != http.MethodGet {
			methodNotAllowed(w)
			return
		}
		after, err := parseNonNegativeInt64(r.URL.Query().Get("after"))
		if err != nil {
			failCode(w, http.StatusBadRequest, "AGENT_TRAFFIC_EVENT_CURSOR_INVALID", err.Error())
			return
		}
		limit, err := parseNonNegativeInt(r.URL.Query().Get("limit"))
		if err != nil {
			failCode(w, http.StatusBadRequest, "AGENT_TRAFFIC_EVENT_CURSOR_INVALID", err.Error())
			return
		}
		page, err := s.tasks.Events(id, after, limit)
		if errors.Is(err, os.ErrNotExist) {
			failCode(w, http.StatusNotFound, "AGENT_TRAFFIC_TASK_NOT_FOUND", "任务不存在")
			return
		}
		if errors.Is(err, core.ErrInvalidEventCursor) {
			failCode(w, http.StatusBadRequest, "AGENT_TRAFFIC_EVENT_CURSOR_INVALID", err.Error())
			return
		}
		if err != nil {
			failCode(w, http.StatusInternalServerError, "AGENT_TRAFFIC_OUTPUT_READ_FAILED", "读取任务事件失败")
			return
		}
		ok(w, page)
		return
	}
	if len(parts) == 3 && parts[2] == "result" {
		if r.Method != http.MethodGet {
			methodNotAllowed(w)
			return
		}
		if _, found := s.tasks.Get(id); !found {
			failCode(w, http.StatusNotFound, "AGENT_TRAFFIC_TASK_NOT_FOUND", "任务不存在")
			return
		}
		result, err := s.tasks.Result(id)
		if errors.Is(err, os.ErrNotExist) {
			failCode(w, http.StatusConflict, "AGENT_TRAFFIC_RESULT_NOT_READY", "任务结果尚未就绪")
			return
		}
		if err != nil {
			failCode(w, http.StatusInternalServerError, "AGENT_TRAFFIC_OUTPUT_READ_FAILED", "读取任务结果失败")
			return
		}
		ok(w, result)
		return
	}
	fail(w, 404, "任务接口不存在")
}

func (s *Server) iperfServerStart(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		methodNotAllowed(w)
		return
	}
	var req iperf.ServerRequest
	if !decode(w, r, &req) {
		return
	}
	toolPath, err := s.tools.RequireIperf3(r.Context())
	if err != nil {
		failTool(w, err)
		return
	}
	runner, err := iperf.ServerRunner(toolPath, req)
	if err != nil {
		failTrafficError(w, err)
		return
	}
	task, err := s.tasks.Start("iperf_server", req, nil, runner)
	if err != nil {
		conflictTask(w, err, task)
		return
	}
	ok(w, task)
}
func (s *Server) iperfClientStart(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		methodNotAllowed(w)
		return
	}
	var req iperf.ClientRequest
	if !decode(w, r, &req) {
		return
	}
	toolPath, err := s.tools.RequireIperf3(r.Context())
	if err != nil {
		failTool(w, err)
		return
	}
	runner, err := iperf.ClientRunner(toolPath, req)
	if err != nil {
		failTrafficError(w, err)
		return
	}
	task, err := s.tasks.Start("iperf_client", req, nil, runner)
	if err != nil {
		conflictTask(w, err, task)
		return
	}
	ok(w, task)
}
func (s *Server) fpingStart(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		methodNotAllowed(w)
		return
	}
	var req fping.Request
	if !decode(w, r, &req) {
		return
	}
	toolPath, err := s.tools.RequireFping(r.Context())
	if err != nil {
		failTool(w, err)
		return
	}
	runner, err := fping.Runner(toolPath, req)
	if err != nil {
		failTrafficError(w, err)
		return
	}
	task, err := s.tasks.Start("fping", req, nil, runner)
	if err != nil {
		conflictTask(w, err, task)
		return
	}
	ok(w, task)
}
func (s *Server) pingStart(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		methodNotAllowed(w)
		return
	}
	var req pingprobe.Request
	if !decode(w, r, &req) {
		return
	}
	runner, err := pingprobe.Runner(req, s.cfg.PingProbe.DefaultIntervalMS, s.cfg.PingProbe.DefaultTimeoutMS, s.cfg.PingProbe.DefaultPacketSize, s.cfg.PingProbe.DefaultTCPPort, s.cfg.PingProbe.MaxTargets)
	if err != nil {
		fail(w, 400, err.Error())
		return
	}
	task, err := s.tasks.Start("ping_probe", req, nil, runner)
	if err != nil {
		conflictTask(w, err, task)
		return
	}
	ok(w, task)
}
func (s *Server) mrStart(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		methodNotAllowed(w)
		return
	}
	var req mr.Request
	if !decode(w, r, &req) {
		return
	}
	if req.TargetID != "" {
		t, found := s.targets.Get(req.TargetID)
		if !found {
			fail(w, 404, "MR 目标不存在")
			return
		}
		req.Target = t
	}
	if !hasMRItems(req.Items) {
		fail(w, http.StatusBadRequest, "至少选择一个 MR 采集项")
		return
	}
	collectorPath, err := s.tools.RequireMRCollector(r.Context())
	if err != nil {
		failTool(w, err)
		return
	}
	if req.Fping.Enabled && hasFpingTargets(req.Fping.Targets) {
		if _, err := s.tools.RequireFping(r.Context()); err != nil {
			failTool(w, err)
			return
		}
	}
	if req.Iperf.Enabled {
		if _, err := s.tools.RequireIperf3(r.Context()); err != nil {
			failTool(w, err)
			return
		}
	}
	runner, err := mr.SidecarRunner(collectorPath, s.cfg.BaseDir, req, req.Fping, s.cfg.FpingPath(), s.cfg.IperfPath())
	if err != nil {
		fail(w, 400, err.Error())
		return
	}
	persisted := req
	persisted.Target = target.Sanitized(req.Target)
	task, err := s.tasks.StartWithPackage("mr_realtime_collect", persisted, target.Sanitized(req.Target), s.cfg.Runtime.AutoPackageOnStop || req.AutoPackageOnStop, runner)
	if err != nil {
		conflictTask(w, err, task)
		return
	}
	ok(w, task)
}

var mrRawFiles = map[string]string{"mesh_link": "mesh_link_raw.log", "channel_busy": "channel_busy_raw.log", "fping_samples": "fping_v5_samples.jsonl", "fping_summary": "fping_v5_final_summary.json", "fping_raw": "fping_v5_raw.log", "switch_history": "switch_history_latest.log"}

func (s *Server) mrLive(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	task, found := s.currentMRTask()
	if !found {
		ok(w, map[string]any{"success": true, "running": false, "message": "当前没有运行中的车载 MR 在线收集任务"})
		return
	}
	dir, _ := s.tasks.TaskDir(task.TaskID)
	payload := map[string]any{"success": true, "running": task.Status == core.Running || task.Status == core.Stopping, "task_id": task.TaskID, "mr_status": task, "link_status": map[string]any{"available": false, "message": "暂无实时链路数据"}, "fping_status": map[string]any{}, "iperf_status": map[string]any{}}
	for key, name := range map[string]string{"mr_status": "live_mr_status.json", "link_status": "live_link_status.json", "fping_status": "live_fping_status.json", "iperf_status": "live_iperf_status.json"} {
		if value, err := readJSONMap(filepath.Join(dir, "view", name)); err == nil {
			payload[key] = value
		}
	}
	ok(w, payload)
}

func (s *Server) mrRawTail(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	name := strings.TrimSpace(r.URL.Query().Get("name"))
	filename, okName := mrRawFiles[name]
	if !okName {
		fail(w, http.StatusBadRequest, "不支持的 raw 文件名称")
		return
	}
	tail := 200
	if value, err := strconv.Atoi(r.URL.Query().Get("tail")); err == nil && value > 0 {
		tail = value
	}
	if tail > 1000 {
		tail = 1000
	}
	task, found := s.currentMRTask()
	if !found {
		ok(w, map[string]any{"success": true, "running": false, "name": name, "file": "raw/" + filename, "exists": false, "lines": []string{}, "message": "当前没有 MR 采集任务"})
		return
	}
	dir, _ := s.tasks.TaskDir(task.TaskID)
	lines, exists, size, updated, err := readTail(filepath.Join(dir, "raw", filename), tail)
	if err != nil {
		fail(w, http.StatusInternalServerError, "读取 raw 日志失败: "+err.Error())
		return
	}
	data := map[string]any{"success": true, "running": task.Status == core.Running || task.Status == core.Stopping, "task_id": task.TaskID, "name": name, "file": "raw/" + filename, "exists": exists, "size": size, "updated_at": updated, "tail": tail, "lines": lines}
	if !exists || size == 0 {
		data["message"] = "文件不存在或尚未生成"
	}
	ok(w, data)
}

func (s *Server) mrRawSummary(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	task, found := s.currentMRTask()
	if !found {
		ok(w, map[string]any{"success": true, "running": false, "files": map[string]any{}})
		return
	}
	dir, _ := s.tasks.TaskDir(task.TaskID)
	files := map[string]any{}
	for name, filename := range mrRawFiles {
		exists, size, updated, _ := statFile(filepath.Join(dir, "raw", filename))
		files[name] = map[string]any{"file": "raw/" + filename, "exists": exists, "size": size, "updated_at": updated}
	}
	ok(w, map[string]any{"success": true, "task_id": task.TaskID, "running": task.Status == core.Running || task.Status == core.Stopping, "files": files})
}

func (s *Server) currentMRTask() (core.Task, bool) {
	if task, found := s.tasks.Active("mr_realtime_collect"); found {
		return task, true
	}
	for _, task := range s.tasks.List() {
		if task.TaskType == "mr_realtime_collect" {
			return task, true
		}
	}
	return core.Task{}, false
}
func (s *Server) powerAction(w http.ResponseWriter, action func() error) {
	if err := action(); err != nil {
		ok(w, map[string]any{"success": false, "power": s.power.Status(), "error": err.Error()})
		return
	}
	ok(w, map[string]any{"success": true, "power": s.power.Status()})
}
func hasFpingTargets(targets []mr.FpingTarget) bool {
	for _, target := range targets {
		if strings.TrimSpace(target.Host) != "" {
			return true
		}
	}
	return false
}

func hasMRItems(items mr.Items) bool {
	return items.TerminalMonitor || items.MeshLink || items.ChannelBusy || items.APRadioStatistics || items.SwitchHistory || items.InterfaceRate || items.WirelessRSSI || items.WirelessStatus
}
func readJSONMap(path string) (map[string]any, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var value map[string]any
	if err := json.Unmarshal(b, &value); err != nil {
		return nil, err
	}
	return value, nil
}
func readTail(path string, tail int) ([]string, bool, int64, string, error) {
	info, err := os.Stat(path)
	if errors.Is(err, os.ErrNotExist) {
		return []string{}, false, 0, "", nil
	}
	if err != nil {
		return nil, false, 0, "", err
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, true, info.Size(), info.ModTime().Format(time.RFC3339Nano), err
	}
	text := strings.TrimRight(strings.ToValidUTF8(string(b), "�"), "\r\n")
	if text == "" {
		return []string{}, true, info.Size(), info.ModTime().Format(time.RFC3339Nano), nil
	}
	lines := strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n")
	if len(lines) > tail {
		lines = lines[len(lines)-tail:]
	}
	return lines, true, info.Size(), info.ModTime().Format(time.RFC3339Nano), nil
}

func statFile(path string) (bool, int64, string, error) {
	info, err := os.Stat(path)
	if errors.Is(err, os.ErrNotExist) {
		return false, 0, "", nil
	}
	if err != nil {
		return false, 0, "", err
	}
	return true, info.Size(), info.ModTime().Format(time.RFC3339Nano), nil
}
func (s *Server) stopType(w http.ResponseWriter, r *http.Request, taskType string) {
	if r.Method != http.MethodPost {
		methodNotAllowed(w)
		return
	}
	task, err := s.tasks.StopType(taskType)
	if err != nil {
		fail(w, 400, err.Error())
		return
	}
	ok(w, task)
}
func (s *Server) typeStatus(w http.ResponseWriter, r *http.Request, taskType string) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	task, found := s.tasks.Active(taskType)
	if !found {
		ok(w, map[string]any{"task_type": taskType, "status": "idle"})
		return
	}
	ok(w, task)
}

func (s *Server) packagesRoot(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	items, err := s.packages.List()
	if err != nil {
		fail(w, 500, err.Error())
		return
	}
	ok(w, items)
}
func (s *Server) packageItem(w http.ResponseWriter, r *http.Request, parts []string) {
	id := parts[1]
	if len(parts) == 3 && parts[2] == "download" {
		if r.Method != http.MethodGet {
			methodNotAllowed(w)
			return
		}
		path, err := s.packages.Path(id)
		if err != nil {
			fail(w, 404, "采集包不存在")
			return
		}
		w.Header().Set("Content-Disposition", fmt.Sprintf("attachment; filename=%q", id+".zip"))
		http.ServeFile(w, r, path)
		return
	}
	if len(parts) == 2 && r.Method == http.MethodDelete {
		if err := s.packages.Delete(id); err != nil {
			fail(w, 404, "采集包不存在")
			return
		}
		ok(w, map[string]any{"deleted": id})
		return
	}
	methodNotAllowed(w)
}

func (s *Server) auth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !s.cfg.Security.EnableAuth {
			next.ServeHTTP(w, r)
			return
		}
		actual := r.Header.Get("X-Agent-Token")
		expected := s.cfg.Security.Token
		if len(actual) != len(expected) || subtle.ConstantTimeCompare([]byte(actual), []byte(expected)) != 1 {
			fail(w, 401, "X-Agent-Token 无效")
			return
		}
		next.ServeHTTP(w, r)
	})
}
func (s *Server) requireMethod(w http.ResponseWriter, r *http.Request, method string, fn func()) {
	if r.Method != method {
		methodNotAllowed(w)
		return
	}
	fn()
}

func decode(w http.ResponseWriter, r *http.Request, value any) bool {
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 2<<20))
	dec.DisallowUnknownFields()
	if err := dec.Decode(value); err != nil {
		fail(w, 400, "JSON 请求无效: "+err.Error())
		return false
	}
	return true
}
func ok(w http.ResponseWriter, data any) { writeJSON(w, 200, map[string]any{"ok": true, "data": data}) }
func fail(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]any{"ok": false, "error": map[string]any{"message": message}})
}
func failCode(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]any{"ok": false, "error": map[string]any{"code": code, "message": message}})
}
func failTool(w http.ResponseWriter, err error) {
	var unavailable *toolmanager.UnavailableError
	if !errors.As(err, &unavailable) {
		fail(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusBadRequest, map[string]any{
		"ok": false,
		"error": map[string]any{
			"code":           unavailable.Code,
			"message":        unavailable.Message,
			"path":           unavailable.Path,
			"hint":           unavailable.Hint,
			"required_files": unavailable.RequiredFiles,
		},
	})
}
func failTrafficError(w http.ResponseWriter, err error) {
	var fpingError *fping.ProtocolError
	if errors.As(err, &fpingError) {
		failCode(w, http.StatusBadRequest, fpingError.Code, fpingError.Message)
		return
	}
	var iperfError *iperf.ProtocolError
	if errors.As(err, &iperfError) {
		failCode(w, http.StatusBadRequest, iperfError.Code, iperfError.Message)
		return
	}
	failCode(w, http.StatusBadRequest, "AGENT_TRAFFIC_INVALID_CONFIG", err.Error())
}

func parseNonNegativeInt64(value string) (int64, error) {
	if value == "" {
		return 0, nil
	}
	parsed, err := strconv.ParseInt(value, 10, 64)
	if err != nil || parsed < 0 {
		return 0, fmt.Errorf("after 必须是非负整数")
	}
	return parsed, nil
}

func parseNonNegativeInt(value string) (int, error) {
	if value == "" {
		return 0, nil
	}
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed < 0 {
		return 0, fmt.Errorf("limit 必须是非负整数")
	}
	return parsed, nil
}
func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func methodNotAllowed(w http.ResponseWriter) { fail(w, 405, "请求方法不支持") }
func conflictTask(w http.ResponseWriter, err error, task core.Task) {
	writeJSON(w, 409, map[string]any{"ok": false, "error": map[string]any{"message": err.Error(), "task_id": task.TaskID}})
}
func recoverMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				fail(w, 500, fmt.Sprintf("内部错误: %v", rec))
			}
		}()
		next.ServeHTTP(w, r)
	})
}
