package api

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"netconsole-agent/internal/config"
	"netconsole-agent/internal/core"
	"netconsole-agent/internal/packagex"
	"netconsole-agent/internal/target"
)

func TestPingAndStatus(t *testing.T) {
	root := t.TempDir()
	cfg := &config.Config{BaseDir: root}
	cfg.Agent.ID = "test-agent"
	cfg.Agent.Name = "Test Agent"
	cfg.Agent.ListenHost = "127.0.0.1"
	cfg.Agent.ListenPort = 18080
	cfg.Agent.DataDir = "data"
	cfg.Agent.LogDir = "logs"
	cfg.Agent.PackageDir = "packages"
	store, err := target.Open(filepath.Join(root, "targets.json"))
	if err != nil {
		t.Fatal(err)
	}
	packager := &packagex.Packager{Dir: cfg.PackagePath(), AgentID: cfg.Agent.ID, AgentName: cfg.Agent.Name, Version: "test"}
	manager, err := core.NewManager(cfg.DataPath(), packager, true)
	if err != nil {
		t.Fatal(err)
	}
	handler := New(cfg, store, manager, packager, "test").Handler()
	for _, path := range []string{"/api/v1/ping", "/api/v1/status", "/api/v1/capabilities"} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("%s status=%d body=%s", path, rec.Code, rec.Body.String())
		}
		if got := rec.Header().Get("Content-Type"); got != "application/json; charset=utf-8" {
			t.Fatalf("content type=%q", got)
		}
		if path == "/api/v1/capabilities" {
			for _, field := range []string{`"ping_probe":true`, `"tcp_ping_probe":true`, `"task_events":true`, `"task_result":true`, `"online_mr_collection":true`, `"iperf_server"`, `"fping"`} {
				if !strings.Contains(rec.Body.String(), field) {
					t.Fatalf("missing %s body=%s", field, rec.Body.String())
				}
			}
		}
	}
}

func TestToolsStatusAndStructuredIperfError(t *testing.T) {
	root := t.TempDir()
	cfg := &config.Config{BaseDir: root}
	cfg.Agent.ID = "test-agent"
	cfg.Agent.Name = "Test Agent"
	cfg.Agent.ListenHost = "127.0.0.1"
	cfg.Agent.ListenPort = 18080
	cfg.Agent.DataDir = "data"
	cfg.Agent.LogDir = "logs"
	cfg.Agent.PackageDir = "packages"
	cfg.Tools.Iperf3WindowsX64 = "./tools/windows-x64/iperf3/iperf3.exe"
	cfg.Tools.FpingWindowsX64 = "./tools/windows-x64/fping/fping.exe"
	store, err := target.Open(filepath.Join(root, "targets.json"))
	if err != nil {
		t.Fatal(err)
	}
	packager := &packagex.Packager{Dir: cfg.PackagePath(), AgentID: cfg.Agent.ID, AgentName: cfg.Agent.Name, Version: "test"}
	manager, err := core.NewManager(cfg.DataPath(), packager, true)
	if err != nil {
		t.Fatal(err)
	}
	handler := New(cfg, store, manager, packager, "test").Handler()
	status := httptest.NewRecorder()
	handler.ServeHTTP(status, httptest.NewRequest(http.MethodGet, "/api/v1/tools/status", nil))
	if status.Code != http.StatusOK || !strings.Contains(status.Body.String(), `"iperf3"`) {
		t.Fatalf("status=%d body=%s", status.Code, status.Body.String())
	}
	request := httptest.NewRequest(http.MethodPost, "/api/v1/iperf/server/start", bytes.NewBufferString(`{"bind":"127.0.0.1","port":5201,"protocol":"tcp","extra_args":[]}`))
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusBadRequest || !strings.Contains(response.Body.String(), `"path"`) || !strings.Contains(response.Body.String(), `"hint"`) {
		t.Fatalf("status=%d body=%s", response.Code, response.Body.String())
	}
	fpingRequest := httptest.NewRequest(http.MethodPost, "/api/v1/fping/start", bytes.NewBufferString(`{"targets":["127.0.0.1"],"count":1}`))
	fpingRequest.Header.Set("Content-Type", "application/json")
	fpingResponse := httptest.NewRecorder()
	handler.ServeHTTP(fpingResponse, fpingRequest)
	if fpingResponse.Code != http.StatusBadRequest || !strings.Contains(fpingResponse.Body.String(), `"code":"AGENT_TRAFFIC_TOOL_NOT_FOUND"`) {
		t.Fatalf("status=%d body=%s", fpingResponse.Code, fpingResponse.Body.String())
	}
}

func TestTaskEventsResultAndCursorErrors(t *testing.T) {
	root := t.TempDir()
	cfg := &config.Config{BaseDir: root}
	cfg.Agent.ID = "test-agent"
	cfg.Agent.Name = "Test Agent"
	cfg.Agent.ListenHost = "127.0.0.1"
	cfg.Agent.ListenPort = 18080
	cfg.Agent.DataDir = "data"
	cfg.Agent.LogDir = "logs"
	cfg.Agent.PackageDir = "packages"
	store, err := target.Open(filepath.Join(root, "targets.json"))
	if err != nil {
		t.Fatal(err)
	}
	packager := &packagex.Packager{Dir: cfg.PackagePath(), AgentID: cfg.Agent.ID, AgentName: cfg.Agent.Name, Version: "test"}
	manager, err := core.NewManager(cfg.DataPath(), packager, false)
	if err != nil {
		t.Fatal(err)
	}
	task, err := manager.Start("fping", map[string]any{}, nil, func(rt *core.Runtime) error {
		_, _ = rt.Emit("sample", "fping", map[string]any{"rtt_ms": 1.2})
		return rt.WriteResult(map[string]any{"samples": 1}, nil)
	})
	if err != nil {
		t.Fatal(err)
	}
	for deadline := time.Now().Add(2 * time.Second); time.Now().Before(deadline); {
		if current, _ := manager.Get(task.TaskID); current.Status == core.Completed {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	handler := New(cfg, store, manager, packager, "test").Handler()
	events := httptest.NewRecorder()
	handler.ServeHTTP(events, httptest.NewRequest(http.MethodGet, "/api/v1/tasks/"+task.TaskID+"/events?after=0&limit=2", nil))
	if events.Code != http.StatusOK || !strings.Contains(events.Body.String(), `"sequence"`) || !strings.Contains(events.Body.String(), `"next_after"`) {
		t.Fatalf("status=%d body=%s", events.Code, events.Body.String())
	}
	result := httptest.NewRecorder()
	handler.ServeHTTP(result, httptest.NewRequest(http.MethodGet, "/api/v1/tasks/"+task.TaskID+"/result", nil))
	if result.Code != http.StatusOK || !strings.Contains(result.Body.String(), `"samples":1`) || strings.Contains(result.Body.String(), root) {
		t.Fatalf("status=%d body=%s", result.Code, result.Body.String())
	}
	invalid := httptest.NewRecorder()
	handler.ServeHTTP(invalid, httptest.NewRequest(http.MethodGet, "/api/v1/tasks/"+task.TaskID+"/events?after=-1", nil))
	if invalid.Code != http.StatusBadRequest || !strings.Contains(invalid.Body.String(), "AGENT_TRAFFIC_EVENT_CURSOR_INVALID") {
		t.Fatalf("status=%d body=%s", invalid.Code, invalid.Body.String())
	}
	pending, err := manager.Start("ping_probe", map[string]any{}, nil, func(rt *core.Runtime) error {
		<-rt.Ctx.Done()
		return rt.Ctx.Err()
	})
	if err != nil {
		t.Fatal(err)
	}
	notReady := httptest.NewRecorder()
	handler.ServeHTTP(notReady, httptest.NewRequest(http.MethodGet, "/api/v1/tasks/"+pending.TaskID+"/result", nil))
	if notReady.Code != http.StatusConflict || !strings.Contains(notReady.Body.String(), "AGENT_TRAFFIC_RESULT_NOT_READY") {
		t.Fatalf("status=%d body=%s", notReady.Code, notReady.Body.String())
	}
	if _, err := manager.Stop(pending.TaskID); err != nil {
		t.Fatal(err)
	}
	if !manager.WaitAll(2 * time.Second) {
		t.Fatal("pending task did not stop")
	}
}

func TestTargetCRUD(t *testing.T) {
	root := t.TempDir()
	cfg := &config.Config{BaseDir: root}
	cfg.Agent.ID = "test-agent"
	cfg.Agent.Name = "Test Agent"
	cfg.Agent.ListenHost = "127.0.0.1"
	cfg.Agent.ListenPort = 18080
	cfg.Agent.DataDir = "data"
	cfg.Agent.LogDir = "logs"
	cfg.Agent.PackageDir = "packages"
	store, err := target.Open(filepath.Join(root, "targets.json"))
	if err != nil {
		t.Fatal(err)
	}
	packager := &packagex.Packager{Dir: cfg.PackagePath(), AgentID: cfg.Agent.ID, AgentName: cfg.Agent.Name, Version: "test"}
	manager, err := core.NewManager(cfg.DataPath(), packager, true)
	if err != nil {
		t.Fatal(err)
	}
	handler := New(cfg, store, manager, packager, "test").Handler()

	create := httptest.NewRequest(http.MethodPost, "/api/v1/targets", bytes.NewBufferString(`{"id":"local-1","name":"Local","type":"iperf","host":"127.0.0.1","protocol":"local","port":0,"username":"","password":"secret","remark":"test"}`))
	create.Header.Set("Content-Type", "application/json")
	created := httptest.NewRecorder()
	handler.ServeHTTP(created, create)
	if created.Code != http.StatusOK || bytes.Contains(created.Body.Bytes(), []byte(`"secret"`)) {
		t.Fatalf("create status=%d body=%s", created.Code, created.Body.String())
	}

	remove := httptest.NewRequest(http.MethodDelete, "/api/v1/targets/local-1", nil)
	removed := httptest.NewRecorder()
	handler.ServeHTTP(removed, remove)
	if removed.Code != http.StatusOK {
		t.Fatalf("delete status=%d body=%s", removed.Code, removed.Body.String())
	}
}

func TestTokenAuthentication(t *testing.T) {
	root := t.TempDir()
	cfg := &config.Config{BaseDir: root}
	cfg.Agent.ID = "test-agent"
	cfg.Agent.Name = "Test Agent"
	cfg.Agent.ListenHost = "127.0.0.1"
	cfg.Agent.ListenPort = 18080
	cfg.Agent.DataDir = "data"
	cfg.Agent.LogDir = "logs"
	cfg.Agent.PackageDir = "packages"
	cfg.Security.EnableAuth = true
	cfg.Security.Token = "expected-token"
	store, err := target.Open(filepath.Join(root, "targets.json"))
	if err != nil {
		t.Fatal(err)
	}
	packager := &packagex.Packager{Dir: cfg.PackagePath(), AgentID: cfg.Agent.ID, AgentName: cfg.Agent.Name, Version: "test"}
	manager, err := core.NewManager(cfg.DataPath(), packager, true)
	if err != nil {
		t.Fatal(err)
	}
	handler := New(cfg, store, manager, packager, "test").Handler()
	unauthorized := httptest.NewRecorder()
	handler.ServeHTTP(unauthorized, httptest.NewRequest(http.MethodGet, "/api/v1/ping", nil))
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("unauthorized status=%d", unauthorized.Code)
	}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/ping", nil)
	req.Header.Set("X-Agent-Token", "expected-token")
	authorized := httptest.NewRecorder()
	handler.ServeHTTP(authorized, req)
	if authorized.Code != http.StatusOK {
		t.Fatalf("authorized status=%d body=%s", authorized.Code, authorized.Body.String())
	}
	fpingUnauthorized := httptest.NewRecorder()
	fpingRequest := httptest.NewRequest(http.MethodPost, "/api/v1/fping/start", bytes.NewBufferString(`{"targets":["127.0.0.1"],"count":1}`))
	fpingRequest.Header.Set("Content-Type", "application/json")
	handler.ServeHTTP(fpingUnauthorized, fpingRequest)
	if fpingUnauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("fping unauthorized status=%d", fpingUnauthorized.Code)
	}
}
