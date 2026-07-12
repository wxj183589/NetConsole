package core

import (
	"context"
	"os"
	"path/filepath"
	"sync"
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
		if ok && current.Status == Cancelled && current.PackageID != "" {
			if repeated, err := manager.Stop(task.TaskID); err != nil || repeated.Status != Cancelled {
				t.Fatalf("repeated stop task=%#v err=%v", repeated, err)
			}
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
		if !ok || task.Status != Cancelled || task.PackageID == "" {
			t.Fatalf("task=%#v ok=%v", task, ok)
		}
	}
}

func TestEventCursorAndResultPersistence(t *testing.T) {
	root := t.TempDir()
	packager := &packagex.Packager{Dir: filepath.Join(root, "packages"), AgentID: "a1", AgentName: "Agent", Version: "test"}
	manager, err := NewManager(filepath.Join(root, "data"), packager, false)
	if err != nil {
		t.Fatal(err)
	}
	task, err := manager.Start("fping", map[string]any{}, nil, func(rt *Runtime) error {
		for index := 0; index < 3; index++ {
			if _, err := rt.Emit("sample", "fping", map[string]any{"index": index}); err != nil {
				return err
			}
		}
		if err := os.WriteFile(filepath.Join(rt.RawDir, "samples.jsonl"), []byte("{}\n"), 0o600); err != nil {
			return err
		}
		return rt.WriteResult(map[string]any{"samples": 3}, []Artifact{{Name: "samples.jsonl", Kind: "samples"}})
	})
	if err != nil {
		t.Fatal(err)
	}
	for deadline := time.Now().Add(3 * time.Second); time.Now().Before(deadline); {
		if current, _ := manager.Get(task.TaskID); current.Status == Completed {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	page, err := manager.Events(task.TaskID, 0, 2)
	if err != nil || len(page.Events) != 2 || !page.HasMore || page.NextAfter != page.Events[1].Sequence {
		t.Fatalf("page=%#v err=%v", page, err)
	}
	repeated, err := manager.Events(task.TaskID, 0, 2)
	if err != nil || repeated.Events[0].Sequence != page.Events[0].Sequence || repeated.Events[1].Sequence != page.Events[1].Sequence {
		t.Fatalf("repeated=%#v err=%v", repeated, err)
	}
	next, err := manager.Events(task.TaskID, page.NextAfter, 100)
	if err != nil || len(next.Events) == 0 || next.Events[0].Sequence <= page.NextAfter {
		t.Fatalf("next=%#v err=%v", next, err)
	}
	result, err := manager.Result(task.TaskID)
	if err != nil || result.Summary["samples"] != float64(3) || len(result.Artifacts) != 1 || !result.Artifacts[0].Available {
		t.Fatalf("result=%#v err=%v", result, err)
	}
}

func TestEventStoreConcurrentSequenceIsUnique(t *testing.T) {
	store := newEventStore(t.TempDir())
	var wait sync.WaitGroup
	for worker := 0; worker < 8; worker++ {
		wait.Add(1)
		go func() {
			defer wait.Done()
			for index := 0; index < 25; index++ {
				if _, err := store.append("sample", "test", map[string]any{"index": index}); err != nil {
					t.Error(err)
				}
			}
		}()
	}
	wait.Wait()
	page, err := readEventPage("test", store.path, 0, 1000)
	if err != nil || len(page.Events) != 200 {
		t.Fatalf("events=%d err=%v", len(page.Events), err)
	}
	for index, event := range page.Events {
		if event.Sequence != int64(index+1) {
			t.Fatalf("sequence[%d]=%d", index, event.Sequence)
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
