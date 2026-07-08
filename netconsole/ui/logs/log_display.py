from __future__ import annotations

import re


LOG_EVENT_ZH_MAP = {
    "APP_AUTO_CLEANUP_COMPLETED": "自动清理完成",
    "APP_AUTO_CLEANUP_FAILED": "自动清理失败",
    "APP_AUTO_CLEANUP_PARTIAL_FAILED": "自动清理部分失败",
    "APP_START": "软件启动",
    "STARTUP": "启动流程",
    "SITE_LOADED": "局点加载完成",
    "MAIN_WINDOW_CREATED": "主窗口创建完成",
    "MAIN_WINDOW_SHOWN": "主窗口显示完成",
    "ONLINE_MR_UI_STATE_RECONCILED": "车载MR在线采集状态同步",
    "UI_PAGE_PROFILE": "页面性能统计",
    "RAIL_MESH_UI": "MR原始MESH日志分析界面",
    "MESH_MR_LOAD_COMPLETED": "MR日志加载完成",
    "MESH_RENDER_CURRENT_TAB": "MR日志当前页渲染",
    "MESH_RENDER_SOURCE_TABLE": "MR日志源文件表渲染",
    "MESH_CACHE_MISS": "MR日志缓存未命中",
    "MESH_MR_LOAD_STARTED": "MR日志开始加载",
    "MESH_PROFILE_SYNC": "MR日志性能同步",
    "MESH_PAGE_FIRST_SHOW": "MR日志页面首次显示",
    "FEATURE_GATE_LOADED": "功能开关加载完成",
    "PAGE_CREATED": "页面创建",
    "PAGE_PRELOADED": "页面预加载完成",
    "PAGE_FIRST_ACTIVATED": "页面首次激活",
    "PAGE_ACTIVATE_FAILED": "页面激活失败",
    "BACKGROUND_TASK_STARTED": "后台任务开始",
    "BACKGROUND_TASK_STOPPED": "后台任务已停止",
    "BACKGROUND_TASK_STOP_FAILED": "后台任务停止失败",
    "LOGS_CLEARED": "日志中心记录已清空",
    "LOGS_EXPORTED": "日志已导出",
    "LOGS_CURRENT_PAGE_EXPORTED": "当前页日志已导出",
    "LOGS_EXPORT_FAILED": "日志导出失败",
}

DETAIL_KEY_ZH_MAP = {
    "page": "页面",
    "page_id": "页面",
    "page_class": "页面类",
    "phase": "阶段",
    "elapsed_ms": "耗时(ms)",
    "rows": "行数",
    "mr_id": "MR日志ID",
    "generation": "刷新代次",
    "site": "局点",
    "workers_count": "采集线程数",
    "manager_running_count": "管理器运行数",
    "state": "状态",
    "loading": "加载中",
    "hidden": "隐藏",
    "source": "来源",
    "edition": "版本",
    "mode": "模式",
    "task": "任务",
    "status": "状态",
    "error": "错误",
    "reason": "原因",
    "deleted_log_files": "删除日志文件数",
    "deleted_cache_files": "删除缓存文件数",
    "failed": "失败数",
    "freed_bytes": "释放字节数",
    "retention_days": "保留天数",
    "cutoff": "截止时间",
}

DETAIL_VALUE_ZH_MAP = {
    "rail.raw_mesh_log_analysis": "MR原始MESH日志分析",
    "first_show.begin": "首次显示开始",
    "first_show.end": "首次显示结束",
    "refresh": "刷新",
    "load": "加载",
    "switch": "切换",
    "ensure": "确认",
    "ready": "就绪",
    "loading": "加载中",
    "yes": "是",
    "no": "否",
    "internal": "内部版",
    "success": "成功",
    "failed": "失败",
    "partial_failed": "部分失败",
    "preload_all": "预加载全部模块",
    "lazy": "按需加载",
}

LOG_LEVEL_ZH_MAP = {
    "INFO": "信息",
    "WARNING": "警告",
    "ERROR": "错误",
    "DEBUG": "调试",
    "CRITICAL": "严重",
}

_DETAIL_TOKEN_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)=(?P<value>\"[^\"]*\"|'[^']*'|[^\s,;]+)")


def display_log_event(event: str) -> str:
    code = str(event or "").strip()
    if not code:
        return ""
    if code in LOG_EVENT_ZH_MAP:
        return LOG_EVENT_ZH_MAP[code]
    prefix, separator, suffix = code.partition(":")
    if separator and prefix in LOG_EVENT_ZH_MAP:
        return f"{LOG_EVENT_ZH_MAP[prefix]}：{suffix}"
    return f"未知事件：{code}"


def display_log_level(level: str) -> str:
    code = str(level or "").strip().upper()
    return LOG_LEVEL_ZH_MAP.get(code, code)


def display_log_detail(detail: str) -> str:
    text = str(detail or "").strip()
    if not text:
        return ""

    replacements: list[tuple[int, int, str]] = []
    for match in _DETAIL_TOKEN_RE.finditer(text):
        key = match.group("key")
        value = _strip_quotes(match.group("value"))
        display_key = DETAIL_KEY_ZH_MAP.get(key, key)
        display_value = DETAIL_VALUE_ZH_MAP.get(value, value)
        replacements.append((match.start(), match.end(), f"{display_key}={display_value}"))
    if not replacements:
        return DETAIL_VALUE_ZH_MAP.get(text, text)

    parts: list[str] = []
    cursor = 0
    for start, end, replacement in replacements:
        parts.append(text[cursor:start])
        parts.append(replacement)
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def display_log_row(row: dict[str, str]) -> dict[str, str]:
    raw_event = row.get("event", "")
    raw_detail = row.get("detail", "")
    raw_level = row.get("level", "")
    return {
        **row,
        "display_level": display_log_level(raw_level),
        "display_event": display_log_event(raw_event),
        "display_detail": display_log_detail(raw_detail),
        "raw_event": raw_event,
        "raw_detail": raw_detail,
        "raw_level": raw_level,
    }


def _strip_quotes(value: str) -> str:
    text = str(value or "")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text
