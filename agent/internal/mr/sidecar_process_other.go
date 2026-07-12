//go:build !windows

package mr

import (
	"os"
	"os/exec"
)

func prepareSidecarCommand(cmd *exec.Cmd) {}
func stopSidecarProcess(process *os.Process) error {
	if process == nil {
		return nil
	}
	return process.Kill()
}
