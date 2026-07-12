//go:build !windows

package power

import "errors"

func platformSupported() bool              { return false }
func setThreadExecutionState(uint32) error { return errors.New("当前平台不支持防休眠") }
