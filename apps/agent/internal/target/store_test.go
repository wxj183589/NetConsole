package target

import (
	"path/filepath"
	"testing"
)

func TestStoreCRUDMaskAndMaskedImport(t *testing.T) {
	path := filepath.Join(t.TempDir(), "targets.json")
	store, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	created, err := store.Create(Target{ID: "mr-1", Name: "MR", Type: "mr", Host: "127.0.0.1", Protocol: "ssh", Port: 22, Username: "admin", Password: "secret"})
	if err != nil || created.Password != "secret" {
		t.Fatalf("create: %#v %v", created, err)
	}
	if got := store.List(true)[0].Password; got != MaskedPassword {
		t.Fatalf("masked password=%q", got)
	}
	masked := Document{Targets: store.List(true)}
	if err := store.Import(masked); err != nil {
		t.Fatal(err)
	}
	actual, _ := store.Get("mr-1")
	if actual.Password != "secret" {
		t.Fatalf("masked import lost password: %q", actual.Password)
	}
	actual.Name = "MR-2"
	actual.Password = MaskedPassword
	if _, err := store.Update("mr-1", actual); err != nil {
		t.Fatal(err)
	}
	actual, _ = store.Get("mr-1")
	if actual.Name != "MR-2" || actual.Password != "secret" {
		t.Fatalf("update=%#v", actual)
	}
	if err := store.Delete("mr-1"); err != nil {
		t.Fatal(err)
	}
}

func TestStoreRejectsUnsafeID(t *testing.T) {
	store, err := Open(filepath.Join(t.TempDir(), "targets.json"))
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.Create(Target{ID: "../bad", Name: "bad", Type: "mr", Host: "127.0.0.1", Protocol: "local"})
	if err == nil {
		t.Fatal("expected unsafe id error")
	}
}
