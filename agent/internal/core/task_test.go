package core

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"netconsole-agent/internal/packagex"
)

func TestManagerStopsAndPackagesTask(t *testing.T) {
	root := t.TempDir()
	packager := &packagex.Packager{Dir: filepath.Join(root, "packages"), AgentID: "a1", AgentName: "Agent", Version: "test"}
	manager, err := NewManager(filepath.Join(root, "data"), packager, true)
	if err != nil {
		t.Fatal(err)
	}
	task, err := manager.Start("ping_probe", map[string]any{"secret": "******"}, nil, func(rt *Runtime) error { <-rt.Ctx.Done(); return context.Canceled })
	if err != nil {
		t.Fatal(err)
	}
	if _, err := manager.Start("ping_probe", map[string]any{}, nil, func(*Runtime) error { return nil }); err == nil {
		t.Fatal("expected duplicate task conflict")
	}
	if _, err := manager.Stop(task.TaskID); err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		current, ok := manager.Get(task.TaskID)
		if ok && current.Status == Completed && current.PackageID != "" {
			if _, err := os.Stat(filepath.Join(root, "packages", task.TaskID+".zip")); err != nil {
				t.Fatal(err)
			}
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("task did not complete and package")
}

func TestManagerStopAllWaitsForTasks(t *testing.T) {
	root := t.TempDir()
	packager := &packagex.Packager{Dir: filepath.Join(root, "packages"), AgentID: "a1", AgentName: "Agent", Version: "test"}
	manager, err := NewManager(filepath.Join(root, "data"), packager, true)
	if err != nil {
		t.Fatal(err)
	}
	ids := []string{}
	for _, taskType := range []string{"iperf_server", "ping_probe"} {
		task, err := manager.Start(taskType, map[string]any{}, nil, func(rt *Runtime) error { <-rt.Ctx.Done(); return context.Canceled })
		if err != nil {
			t.Fatal(err)
		}
		ids = append(ids, task.TaskID)
	}
	if stopped := manager.StopAll(); len(stopped) != 2 {
		t.Fatalf("stopped=%d", len(stopped))
	}
	if !manager.WaitAll(3 * time.Second) {
		t.Fatal("WaitAll timed out")
	}
	for _, id := range ids {
		task, ok := manager.Get(id)
		if !ok || task.Status != Completed || task.PackageID == "" {
			t.Fatalf("task=%#v ok=%v", task, ok)
		}
	}
}

func TestStartWithPackageOverridesDisabledDefault(t *testing.T) {
	root := t.TempDir()
	packager := &packagex.Packager{Dir: filepath.Join(root, "packages"), AgentID: "a1", AgentName: "Agent", Version: "test"}
	manager, err := NewManager(filepath.Join(root, "data"), packager, false)
	if err != nil {
		t.Fatal(err)
	}
	task, err := manager.StartWithPackage("mr_realtime_collect", map[string]any{}, nil, true, func(*Runtime) error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		final, _ := manager.Get(task.TaskID)
		if final.Status == Completed {
			if final.PackageID == "" {
				t.Fatal("package override was ignored")
			}
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("task did not complete")
}
