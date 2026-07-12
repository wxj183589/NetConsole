//go:build windows

package power

import (
	"fmt"
	"syscall"
)

var setThreadExecutionStateProc = syscall.NewLazyDLL("kernel32.dll").NewProc("SetThreadExecutionState")

func platformSupported() bool { return true }
func setThreadExecutionState(flags uint32) error {
	result, _, callErr := setThreadExecutionStateProc.Call(uintptr(flags))
	if result == 0 {
		if callErr != syscall.Errno(0) {
			return callErr
		}
		return fmt.Errorf("SetThreadExecutionState failed")
	}
	return nil
}
