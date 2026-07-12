package mr

// 命令文本与 netconsole/services/online_mr/collection_commands.py 对齐。
var terminalMonitorCommands = []string{
	"screen-length disable",
	"terminal monitor",
	"terminal logging level 7",
}

var probePrepareCommands = []string{"screen-length disable", "system-view", "probe"}

var periodicCommands = map[string][]string{
	"channel_busy":        {"display clock", "display ar5drv 1 channelbusy"},
	"ap_radio_statistics": {"display clock", "display ar5drv 1 statistics"},
	"wireless_rssi":       {"display clock", "display ar5drv 1 client all rssi"},
	"wireless_status":     {"display clock", "display ar5drv 1 client all status"},
}

var rawNames = map[string]string{
	"channel_busy":        "channel_busy_raw.log",
	"ap_radio_statistics": "ap_radio_statistics_raw.log",
	"wireless_rssi":       "wireless_rssi_raw.log",
	"wireless_status":     "wireless_status_raw.log",
}
