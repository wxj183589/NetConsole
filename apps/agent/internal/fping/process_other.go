//go:build !windows

package fping

import "os/exec"

func prepareCommand(cmd *exec.Cmd) {}
