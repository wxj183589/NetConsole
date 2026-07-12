package power

import "sync"

const (
	esContinuous      uint32 = 0x80000000
	esSystemRequired  uint32 = 0x00000001
	esDisplayRequired uint32 = 0x00000002
)

type Status struct {
	Supported       bool   `json:"supported"`
	Active          bool   `json:"active"`
	DisplayRequired bool   `json:"display_required"`
	Mode            string `json:"mode"`
	LastReason      string `json:"last_reason"`
	LastError       string `json:"last_error"`
}

type Manager struct {
	mu     sync.RWMutex
	status Status
}

func New() *Manager { return &Manager{status: Status{Supported: platformSupported(), Mode: "off"}} }
func (m *Manager) PreventSleep(reason string) error {
	return m.apply(esContinuous|esSystemRequired, "system_required", reason)
}
func (m *Manager) PreventSleepDisplay(reason string) error {
	return m.apply(esContinuous|esSystemRequired|esDisplayRequired, "system_and_display_required", reason)
}
func (m *Manager) Restore(reason string) error { return m.apply(esContinuous, "off", reason) }
func (m *Manager) SetTaskRunning(running, keepDisplay bool) {
	if running && keepDisplay {
		_ = m.PreventSleepDisplay("task_running")
	} else {
		_ = m.PreventSleep("all_tasks_stopped")
	}
}
func (m *Manager) Status() Status { m.mu.RLock(); defer m.mu.RUnlock(); return m.status }
func (m *Manager) apply(flags uint32, mode, reason string) error {
	err := setThreadExecutionState(flags)
	m.mu.Lock()
	defer m.mu.Unlock()
	m.status.LastReason = reason
	if err != nil {
		m.status.LastError = err.Error()
		if !m.status.Supported {
			m.status.Mode = "unsupported"
		}
		return err
	}
	m.status.Active = mode != "off"
	m.status.DisplayRequired = mode == "system_and_display_required"
	m.status.Mode = mode
	m.status.LastError = ""
	return nil
}
