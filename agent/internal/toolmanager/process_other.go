//go:build !windows

package toolmanager

import "os/exec"

func prepareCommand(_ *exec.Cmd) {}
