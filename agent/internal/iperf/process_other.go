//go:build !windows

package iperf

import "os/exec"

func prepareCommand(_ *exec.Cmd) {}
