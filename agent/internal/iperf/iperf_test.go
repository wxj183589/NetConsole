package iperf

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLastMeasuredMbps(t *testing.T) {
	path := filepath.Join(t.TempDir(), "iperf.log")
	text := "[  5] 0.00-1.00 sec  50.0 MBytes  400 Mbits/sec\n[  5] 0.00-2.00 sec  1.20 GBytes  5.15 Gbits/sec receiver\n"
	if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	value, found := lastMeasuredMbps(path)
	if !found || value != 5150 {
		t.Fatalf("value=%v found=%v", value, found)
	}
}

func TestRejectsRoleOverrideInExtraArgs(t *testing.T) {
	if err := validateExtraArgs([]string{"--logfile", "other.log"}); err == nil {
		t.Fatal("expected blocked logfile")
	}
	if err := validateExtraArgs([]string{"--connect-timeout", "1000"}); err != nil {
		t.Fatal(err)
	}
}
