//go:build windows

package mr

import (
	"os"
	"os/exec"
	"syscall"
)

func prepareSidecarCommand(cmd *exec.Cmd) { cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true} }
func stopSidecarProcess(process *os.Process) error {
	if process == nil {
		return nil
	}
	return process.Kill()
}
