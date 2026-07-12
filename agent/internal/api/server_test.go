package api

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

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
	for _, path := range []string{"/api/v1/ping", "/api/v1/status"} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("%s status=%d body=%s", path, rec.Code, rec.Body.String())
		}
		if got := rec.Header().Get("Content-Type"); got != "application/json; charset=utf-8" {
			t.Fatalf("content type=%q", got)
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
}
