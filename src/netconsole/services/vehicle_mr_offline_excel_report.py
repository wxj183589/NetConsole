from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from netconsole.services.excel_report_utils import append_rows_sheet, format_link_state


REPORT_VERSION = "vehicle_mr_offline_diagnostic_v2"
DEFAULT_ROW_LIMIT = 5000


class VehicleMrOfflineExcelReportExporter:
    def __init__(self, *, include_detail_sheets: bool = False, include_trend_charts: bool = False, row_limit: int = DEFAULT_ROW_LIMIT) -> None:
        self.include_detail_sheets = include_detail_sheets
        self.include_trend_charts = include_trend_charts
        self.row_limit = max(100, int(row_limit or DEFAULT_ROW_LIMIT))

    def export(self, session_dir: Path, output_path: Path) -> Path:
        session_dir = Path(session_dir)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        data = _VehicleMrReportData(session_dir, db_path, row_limit=self.row_limit)

        workbook = Workbook()
        workbook.remove(workbook.active)
        for name, headers, rows, empty_message in data.default_sheets():
            append_rows_sheet(workbook, name, headers, rows, empty_message=empty_message, max_width=56.0)

        if self.include_detail_sheets:
            for name, headers, rows, empty_message in data.detail_sheets():
                append_rows_sheet(workbook, name, headers, rows, empty_message=empty_message, max_width=56.0)
        if self.include_trend_charts:
            for name, headers, rows, empty_message in data.trend_table_sheets():
                append_rows_sheet(workbook, name, headers, rows, empty_message=empty_message, max_width=48.0)

        workbook.save(output_path)
        return output_path


class _VehicleMrReportData:
    def __init__(self, session_dir: Path, db_path: Path, *, row_limit: int) -> None:
        self.session_dir = Path(session_dir)
        self.db_path = Path(db_path)
        self.row_limit = row_limit
        self.meta = self._read_session_meta()
        self._counts_cache: dict[str, int] | None = None

    def default_sheets(self) -> list[tuple[str, list[str], list[list[object]], str]]:
        return [
            ("报告总览", ["项目", "结论/数值", "诊断说明", "证据"], self.overview_rows(), "未读取到可用于生成报告总览的数据。"),
            ("会话信息", ["字段", "值", "说明"], self.session_info_rows(), "缺少 session_meta.json 和 parsed 数据库元信息。"),
            ("数据完整性", ["数据表", "记录数", "完整性结论", "说明"], self.data_integrity_rows(), "未发现 parsed 数据表。"),
            ("质量评分", ["维度", "评分", "等级", "诊断依据"], self.quality_score_rows(), "当前数据不足，无法计算质量评分。"),
            ("时间轴质量概览", ["时间粒度", "Active采样数", "Active Peer数", "平均MR侧RSSI", "最低MR侧RSSI", "fping丢包率(%)", "平均延迟(ms)", "TxBusy最大值", "RxBusy最大值", "质量结论"], self.timeline_rows(), "缺少可对齐的主链路、fping 或空口繁忙度时间序列。"),
            ("fping业务质量", ["时间", "目标IP", "发送", "接收", "丢失", "丢包率(%)", "平均延迟(ms)", "最大延迟(ms)", "Jitter(ms)", "状态", "诊断"], self.fping_quality_rows(), "未采集或未解析 fping 1 秒聚合数据。"),
            ("Mesh主链路区段", ["区段ID", "Radio", "主链路Peer MAC", "开始时间", "结束时间", "采样点数", "平均MR侧RSSI", "最低MR侧RSSI", "最高MR侧RSSI", "事件类型", "fping发送", "fping丢失", "fping丢包率(%)", "平均延迟(ms)", "最大TxBusy", "最大RxBusy", "诊断"], self.active_segment_rows(), "未生成主链路区段数据，请先执行离线解析。"),
            ("Peer质量排名", ["Radio", "对端AP名称", "Peer MAC", "归属站点", "归属区间", "总采样数", "Active采样数", "备链采样数", "Active平均RSSI", "Active最低RSSI", "首次出现", "最后出现", "质量结论"], self.peer_ranking_rows(), "未发现 Peer 采样数据。"),
            ("切换影响分析", ["切换时间", "Radio", "切出AP", "切入AP", "切出RSSI", "切入RSSI", "切换原因", "邻近fping丢包率(%)", "是否影响业务", "诊断建议"], self.switch_impact_rows(), "未发现主链路切换事件。"),
            ("丢包关联分析", ["丢包时间", "目标IP", "丢包率(%)", "平均延迟(ms)", "Active Peer", "MR侧RSSI", "邻近切换", "TxBusy", "RxBusy", "判断"], self.loss_correlation_rows(), "未发现 fping 丢包点，或缺少 fping 数据。"),
            ("异常事件清单", ["事件ID", "事件时间", "事件类型", "级别", "说明", "证据ID"], self.anomaly_rows(), "未发现异常事件。"),
            ("空口繁忙度分析", ["Radio", "样本数", "平均控制信道繁忙度", "最大控制信道繁忙度", "平均TxBusy", "最大TxBusy", "平均RxBusy", "最大RxBusy", "诊断"], self.channel_busy_rows(), "未采集或未解析信道繁忙度数据。"),
            ("射频统计分析", ["Radio", "指标", "样本数", "平均值", "最小值", "最大值", "单位", "诊断"], self.radio_statistics_rows(), "未采集或未解析射频统计数据。"),
            ("接口速率分析", ["接口", "方向", "样本数", "平均PPS", "最大PPS", "平均广播PPS", "最大广播PPS", "平均组播PPS", "最大组播PPS", "诊断"], self.interface_rate_rows(), "未采集或未解析接口速率数据。"),
            ("链路重建与连接异常", ["时间", "Peer/对象", "事件", "RSSI/指标", "原因", "证据ID"], self.rebuild_rows(), "未发现链路重建或连接异常事件。"),
            ("原始证据片段", ["证据ID", "来源Sheet", "事件类型", "采样时间", "源文件", "源行号", "原始/摘要"], self.evidence_rows(), "当前报告没有需要附带的原始证据片段。"),
            ("参数配置", ["配置项", "值", "说明"], self.parameter_rows(), "未读取到参数配置。"),
        ]

    def detail_sheets(self) -> list[tuple[str, list[str], list[list[object]], str]]:
        return [
            ("fping原始样本", ["本地时间", "设备对齐时间", "目标IP", "序号", "状态", "延迟(ms)"], self.fping_sample_rows(), "未导出 fping 原始样本。"),
            ("Mesh链路采样明细", ["采样时间", "设备时间", "Radio", "链路状态", "Peer MAC", "对端AP名称", "MR侧RSSI", "归属站点", "归属区间", "源文件", "源行号"], self.mesh_detail_rows(), "未导出 Mesh 采样明细。"),
        ]

    def trend_table_sheets(self) -> list[tuple[str, list[str], list[list[object]], str]]:
        return [
            ("趋势图表", ["时间", "Active RSSI", "fping丢包率(%)", "平均延迟(ms)", "TxBusy", "RxBusy"], self.timeline_metric_rows(), "未生成趋势图表数据。")
        ]

    def overview_rows(self) -> list[list[object]]:
        counts = self.table_counts()
        stats = self.basic_stats()
        score_rows = self.quality_score_rows()
        numeric_scores = [_num(row[1]) for row in score_rows if row[1] not in (None, "", "N/A")]
        overall = round(sum(numeric_scores) / max(len(numeric_scores), 1), 1) if numeric_scores else "N/A"
        return [
            ["报告类型", "车载MR离线诊断报告", "基于 parsed/online_diagnosis.sqlite 的结构化数据生成", REPORT_VERSION],
            ["当前局点", self.meta.get("site") or "-", "来自 session_meta.json", ""],
            ["MR名称", self.meta.get("mr_name") or self.meta.get("device_name") or "-", "来自 session_meta.json", ""],
            ["采样时间范围", f"{stats.get('start_time') or '-'} ~ {stats.get('end_time') or '-'}", "按 main_link_samples 统计", "main_link_samples"],
            ["综合评分", overall, _score_level_or_na(overall), "质量评分"],
            ["主链路样本数", counts.get("main_link_samples", 0), "ACTIVE/STANDBY 原始采样总数", "main_link_samples"],
            ["主链路切换次数", counts.get("switch_realtime_events", 0), "实时切换日志事件数", "switch_realtime_events"],
            ["fping 1秒聚合数", counts.get("fping_1s_summary", 0), f"平均丢包率 {stats.get('avg_loss', '-')}", "fping_1s_summary"],
            ["平均MR侧RSSI", stats.get("avg_rssi") if stats.get("avg_rssi") is not None else "-", "仅统计 ACTIVE 主链路", "main_link_samples"],
            ["最低MR侧RSSI", stats.get("min_rssi") if stats.get("min_rssi") is not None else "-", "仅统计 ACTIVE 主链路", "main_link_samples"],
            ["最大Tx/RxBusy", f"{stats.get('max_tx_busy', '-')}/{stats.get('max_rx_busy', '-')}", "空口繁忙度风险参考", "channel_busy_records"],
            ["解析问题数", counts.get("online_parse_issues", 0), "非 0 时请查看异常事件和原始证据", "online_parse_issues"],
        ]

    def session_info_rows(self) -> list[list[object]]:
        keys = [
            ("session_id", "会话ID"),
            ("site", "局点"),
            ("mr_name", "MR名称"),
            ("device_name", "设备名称"),
            ("host", "管理地址"),
            ("started_at", "开始时间"),
            ("ended_at", "结束时间"),
            ("status", "采集状态"),
            ("session_type", "会话类型"),
        ]
        rows = [[label, self.meta.get(key) or "-", "session_meta.json"] for key, label in keys]
        rows.append(["parsed数据库", str(self.db_path), "报告结构化数据来源"])
        return rows

    def data_integrity_rows(self) -> list[list[object]]:
        required = {
            "main_link_samples": "Mesh 主链路/备链采样",
            "channel_busy_records": "空口繁忙度",
            "radio_statistics_samples": "射频统计",
            "interface_rate_samples": "接口速率",
            "fping_1s_summary": "fping 1秒聚合",
            "switch_realtime_events": "实时切换事件",
            "active_segments": "主链路区段",
            "analysis_events": "分析事件",
            "online_parse_issues": "解析问题",
            "online_parse_metadata": "解析元数据",
            "time_sync_samples": "时间同步样本",
        }
        counts = self.table_counts()
        rows: list[list[object]] = []
        for table, description in required.items():
            count = counts.get(table, 0)
            if table in {"main_link_samples", "online_parse_metadata"}:
                conclusion = "正常" if count else "缺失"
            else:
                conclusion = "有数据" if count else "无数据"
            rows.append([table, count, conclusion, description])
        return rows

    def quality_score_rows(self) -> list[list[object]]:
        stats = self.basic_stats()
        counts = self.table_counts()
        fping_score: object = "N/A"
        if counts.get("fping_1s_summary", 0) > 0:
            fping_score = round(_bounded(100 - float(stats.get("avg_loss") or 0) * 4 - max(float(stats.get("avg_latency") or 0) - 20, 0) * 0.5), 1)
        rssi = stats.get("avg_rssi")
        mesh_score: object = "N/A" if rssi is None else round(_bounded((float(rssi) - 20) * 4), 1)
        busy_score: object = "N/A"
        if counts.get("channel_busy_records", 0) > 0:
            busy_score = round(_bounded(100 - max(float(stats.get("max_tx_busy") or 0), float(stats.get("max_rx_busy") or 0)) * 0.8), 1)
        integrity_score: object = round(_bounded(100 - max(0, counts.get("online_parse_issues", 0)) * 5), 1)
        switch_score: object = "N/A"
        if counts.get("main_link_samples", 0) > 0 or counts.get("switch_realtime_events", 0) > 0:
            switch_count = float(counts.get("switch_realtime_events", 0))
            switch_score = round(_bounded(100 - min(switch_count, 100) * 0.6), 1)
        return [
            ["业务连通性", fping_score, _score_level_or_na(fping_score), "按 fping 平均丢包率与平均延迟评分；缺数据时不评分"],
            ["Mesh主链路质量", mesh_score, _score_level_or_na(mesh_score), "按 ACTIVE 主链路平均 RSSI 评分；缺数据时不评分"],
            ["空口繁忙度", busy_score, _score_level_or_na(busy_score), "按 TxBusy/RxBusy 最大值评分；缺数据时不评分"],
            ["切换稳定性", switch_score, _score_level_or_na(switch_score), "按主链路切换事件数量评分；缺主链路数据时不评分"],
            ["数据完整性", integrity_score, _score_level_or_na(integrity_score), "按解析问题数量扣分"],
        ]

    def timeline_rows(self) -> list[list[object]]:
        mesh = self._query(
            """
            SELECT substr(replace(COALESCE(NULLIF(device_time, ''), collector_time), 'T', ' '), 1, 16) AS minute_key,
                   COUNT(*), COUNT(DISTINCT peer_mac), ROUND(AVG(ABS(mr_rssi)), 2), MIN(ABS(mr_rssi))
            FROM main_link_samples
            WHERE UPPER(COALESCE(link_state, '')) LIKE 'ACTIVE%' AND COALESCE(NULLIF(device_time, ''), collector_time) IS NOT NULL
            GROUP BY minute_key
            ORDER BY minute_key ASC
            LIMIT ?
            """,
            (self.row_limit,),
        )
        fping = {
            row[0]: row[1:]
            for row in self._query(
                """
                SELECT substr(replace(COALESCE(NULLIF(device_bucket_time, ''), NULLIF(bucket_time, ''), local_bucket_time), 'T', ' '), 1, 16),
                       ROUND(AVG(loss_percent), 2), ROUND(AVG(avg_latency_ms), 2)
                FROM fping_1s_summary
                GROUP BY 1
                ORDER BY 1 ASC
                LIMIT ?
                """,
                (self.row_limit,),
            )
        }
        busy = {
            row[0]: row[1:]
            for row in self._query(
                """
                SELECT substr(replace(device_time, 'T', ' '), 1, 16), MAX(tx_busy), MAX(rx_busy)
                FROM channel_busy_records
                GROUP BY 1
                ORDER BY 1 ASC
                LIMIT ?
                """,
                (self.row_limit,),
            )
        }
        rows: list[list[object]] = []
        for item in mesh:
            minute_key = item[0]
            loss, latency = fping.get(minute_key, (None, None))
            tx_busy, rx_busy = busy.get(minute_key, (None, None))
            rows.append([minute_key, item[1], item[2], item[3], item[4], loss, latency, tx_busy, rx_busy, _timeline_conclusion(item[4], loss, tx_busy, rx_busy)])
        return rows

    def fping_quality_rows(self) -> list[list[object]]:
        rows = self._query(
            """
            SELECT COALESCE(NULLIF(device_bucket_time, ''), NULLIF(bucket_time, ''), local_bucket_time),
                   target_ip, sent, received, COALESCE(lost, sent - received), loss_percent,
                   avg_latency_ms, max_latency_ms, jitter_ms, status
            FROM fping_1s_summary
            ORDER BY COALESCE(NULLIF(device_bucket_time, ''), NULLIF(bucket_time, ''), local_bucket_time) ASC, target_ip ASC
            LIMIT ?
            """,
            (self.row_limit,),
        )
        return [list(row) + [_fping_conclusion(row[5], row[6])] for row in rows]

    def active_segment_rows(self) -> list[list[object]]:
        rows = self._query(
            """
            SELECT s.id, s.radio, s.active_peer_mac, s.start_time, s.end_time, s.sample_count,
                   ROUND(ABS(s.avg_mr_rssi), 2), ABS(s.min_mr_rssi), ABS(s.max_mr_rssi), COALESCE(s.event_type, ''),
                   m.ping_sent, m.ping_lost, m.ping_loss_percent, m.avg_latency_ms, m.max_tx_busy, m.max_rx_busy
            FROM active_segments s
            LEFT JOIN active_segment_metrics m ON m.segment_id = s.id
            ORDER BY s.start_time ASC, s.id ASC
            LIMIT ?
            """,
            (self.row_limit,),
        )
        return [list(row) + [_segment_conclusion(row[7], row[12], row[14], row[15])] for row in rows]

    def peer_ranking_rows(self) -> list[list[object]]:
        rows = self._query(
            """
            SELECT radio,
                   COALESCE(NULLIF(resolved_peer_name, ''), NULLIF(peer_name, ''), peer_mac),
                   peer_mac, belong_station, belong_section,
                   COUNT(*),
                   SUM(CASE WHEN UPPER(COALESCE(link_state, '')) LIKE 'ACTIVE%' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN UPPER(COALESCE(link_state, '')) LIKE '%STANDBY%' OR UPPER(COALESCE(link_state, '')) LIKE '%BACKUP%' THEN 1 ELSE 0 END),
                   ROUND(AVG(CASE WHEN UPPER(COALESCE(link_state, '')) LIKE 'ACTIVE%' THEN ABS(mr_rssi) END), 2),
                   MIN(CASE WHEN UPPER(COALESCE(link_state, '')) LIKE 'ACTIVE%' THEN ABS(mr_rssi) END),
                   MIN(collector_time), MAX(collector_time)
            FROM main_link_samples
            GROUP BY radio, peer_mac
            ORDER BY 7 DESC, 9 DESC
            LIMIT ?
            """,
            (self.row_limit,),
        )
        return [list(row) + [_peer_conclusion(row[6], row[8], row[9])] for row in rows]

    def switch_impact_rows(self) -> list[list[object]]:
        fping_points = self._timed_rows(
            """
            SELECT COALESCE(NULLIF(device_bucket_time, ''), NULLIF(bucket_time, ''), local_bucket_time), loss_percent
            FROM fping_1s_summary
            ORDER BY 1 ASC
            LIMIT ?
            """,
            (self.row_limit,),
        )
        rows = self._query(
            """
            SELECT device_time, NULL, old_peer_name, new_peer_name, old_rssi, new_rssi, switch_reason_text
            FROM switch_realtime_events
            ORDER BY device_time ASC, id ASC
            LIMIT ?
            """,
            (self.row_limit,),
        )
        output: list[list[object]] = []
        for row in rows:
            loss = _nearest_value(fping_points, row[0], max_seconds=3)
            impacted = _is_switch_impacted(row[4], row[5], loss)
            output.append([row[0], row[1] or "-", row[2] or "-", row[3] or "-", row[4], row[5], row[6] or "-", loss if loss is not None else "-", "是" if impacted else "否", _switch_suggestion(row[4], row[5], loss)])
        return output

    def loss_correlation_rows(self) -> list[list[object]]:
        active_points = self._timed_rows(
            """
            SELECT collector_time, COALESCE(NULLIF(resolved_peer_name, ''), NULLIF(peer_name, ''), peer_mac), ABS(mr_rssi)
            FROM main_link_samples
            WHERE UPPER(COALESCE(link_state, '')) LIKE 'ACTIVE%'
            ORDER BY collector_time ASC
            LIMIT ?
            """,
            (self.row_limit,),
        )
        switch_points = self._timed_rows("SELECT device_time, switch_reason_text FROM switch_realtime_events ORDER BY device_time ASC LIMIT ?", (self.row_limit,))
        busy_points = self._timed_rows("SELECT device_time, tx_busy, rx_busy FROM channel_busy_records ORDER BY device_time ASC LIMIT ?", (self.row_limit,))
        losses = self._query(
            """
            SELECT COALESCE(NULLIF(device_bucket_time, ''), NULLIF(bucket_time, ''), local_bucket_time),
                   target_ip, loss_percent, avg_latency_ms
            FROM fping_1s_summary
            WHERE COALESCE(loss_percent, 0) > 0 OR COALESCE(lost, 0) > 0
            ORDER BY 1 ASC
            LIMIT ?
            """,
            (self.row_limit,),
        )
        output: list[list[object]] = []
        for loss in losses:
            active = _nearest_tuple(active_points, loss[0], max_seconds=3)
            switch = _nearest_tuple(switch_points, loss[0], max_seconds=3)
            busy = _nearest_tuple(busy_points, loss[0], max_seconds=5)
            peer = active[1] if active else "-"
            rssi = active[2] if active else "-"
            tx_busy = busy[1] if busy else "-"
            rx_busy = busy[2] if busy else "-"
            output.append([loss[0], loss[1], loss[2], loss[3], peer, rssi, switch[1] if switch else "否", tx_busy, rx_busy, _loss_judgment(loss[2], rssi, switch, tx_busy, rx_busy)])
        return output

    def anomaly_rows(self) -> list[list[object]]:
        rows = [
            [f"AE-{row[0]}", row[1], row[2], row[3], row[4], f"AE-{row[0]}"]
            for row in self._query(
                "SELECT id, collector_time, event_type, severity, summary_text FROM analysis_events ORDER BY collector_time ASC, id ASC LIMIT ?",
                (self.row_limit,),
            )
        ]
        rows.extend(
            [f"PI-{row[0]}", "-", row[3], row[4], row[5], f"PI-{row[0]}"]
            for row in self._query("SELECT id, raw_file, line_number, issue_type, severity, message FROM online_parse_issues ORDER BY id ASC LIMIT ?", (self.row_limit,))
        )
        if not rows:
            rows.extend(self._derived_anomaly_rows())
        return rows[: self.row_limit]

    def channel_busy_rows(self) -> list[list[object]]:
        rows = self._query(
            """
            SELECT radio, COUNT(*), ROUND(AVG(ctl_busy), 2), MAX(ctl_busy),
                   ROUND(AVG(tx_busy), 2), MAX(tx_busy), ROUND(AVG(rx_busy), 2), MAX(rx_busy)
            FROM channel_busy_records
            GROUP BY radio
            ORDER BY radio ASC
            """
        )
        return [list(row) + [_busy_conclusion(row[3], row[5], row[7])] for row in rows]

    def radio_statistics_rows(self) -> list[list[object]]:
        rows = self._query(
            """
            SELECT radio, metric_name, COUNT(*), ROUND(AVG(metric_value), 2), MIN(metric_value), MAX(metric_value), COALESCE(metric_unit, '')
            FROM radio_statistics_samples
            GROUP BY radio, metric_name
            ORDER BY radio ASC, metric_name ASC
            LIMIT ?
            """,
            (self.row_limit,),
        )
        return [list(row) + [_generic_metric_conclusion(row[1], row[5])] for row in rows]

    def interface_rate_rows(self) -> list[list[object]]:
        rows = self._query(
            """
            SELECT COALESCE(NULLIF(interface_normalized, ''), interface_name), direction, COUNT(*),
                   ROUND(AVG(total_pps), 2), MAX(total_pps),
                   ROUND(AVG(broadcast_pps), 2), MAX(broadcast_pps),
                   ROUND(AVG(multicast_pps), 2), MAX(multicast_pps)
            FROM interface_rate_samples
            GROUP BY COALESCE(NULLIF(interface_normalized, ''), interface_name), direction
            ORDER BY 1 ASC, direction ASC
            LIMIT ?
            """,
            (self.row_limit,),
        )
        return [list(row) + [_interface_conclusion(row[4], row[6], row[8])] for row in rows]

    def rebuild_rows(self) -> list[list[object]]:
        rows = [
            [row[1], "-", row[2], "-", row[4], f"AE-{row[0]}"]
            for row in self._query(
                """
                SELECT id, collector_time, event_type, severity, summary_text
                FROM analysis_events
                WHERE UPPER(COALESCE(event_type, '')) LIKE '%REBUILD%'
                   OR UPPER(COALESCE(event_type, '')) LIKE '%RESET%'
                   OR UPPER(COALESCE(event_type, '')) LIKE '%DISCONNECT%'
                ORDER BY collector_time ASC, id ASC
                LIMIT ?
                """,
                (self.row_limit,),
            )
        ]
        rows.extend(
            [row[0], row[2] or row[3] or "-", "空链路/强制切换", row[4], row[6] or "-", f"SW-{index}"]
            for index, row in enumerate(
                self._query(
                    """
                    SELECT device_time, old_peer_name, new_peer_name, new_peer_mac, new_rssi, switch_reason_code, switch_reason_text
                    FROM switch_realtime_events
                    WHERE new_peer_mac IS NULL OR new_peer_mac = '' OR new_peer_mac = '0000-0000-0000' OR new_peer_name IN ('NA', 'N/A', '-')
                    ORDER BY device_time ASC, id ASC
                    LIMIT ?
                    """,
                    (self.row_limit,),
                ),
                1,
            )
        )
        return rows

    def evidence_rows(self) -> list[list[object]]:
        rows = [
            [f"AE-{row[0]}", "异常事件清单", row[2], row[1], row[5] or "-", _line_range(row[6], row[7]), row[4] or "-"]
            for row in self._query(
                "SELECT id, collector_time, event_type, severity, summary_text, raw_file, raw_line_start, raw_line_end FROM analysis_events ORDER BY id ASC LIMIT ?",
                (self.row_limit,),
            )
        ]
        rows.extend(
            [f"PI-{row[0]}", "异常事件清单", row[3], "-", row[1] or "-", row[2] or "-", row[6] or row[5] or "-"]
            for row in self._query("SELECT id, raw_file, line_number, issue_type, severity, message, raw_text FROM online_parse_issues ORDER BY id ASC LIMIT ?", (self.row_limit,))
        )
        rows.extend(
            [f"SW-{index}", "切换影响分析", "主链路切换", row[0], row[1] or "-", _line_range(row[2], row[3]), row[4] or "-"]
            for index, row in enumerate(
                self._query("SELECT device_time, raw_file, raw_line_start, raw_line_end, switch_reason_text FROM switch_realtime_events ORDER BY device_time ASC, id ASC LIMIT 200"),
                1,
            )
        )
        return rows[: self.row_limit]

    def parameter_rows(self) -> list[list[object]]:
        metadata = self._latest_metadata()
        return [
            ["报告版本", REPORT_VERSION, "导出器版本"],
            ["默认明细导出", "关闭", "默认只保留诊断级 Sheet，避免 Excel 文件过大"],
            ["默认趋势图表", "关闭", "趋势数据可在 UI 动态图表查看，本报告默认不展开大量趋势 Sheet"],
            ["单Sheet行数上限", self.row_limit, "防止误导出超大明细造成卡顿"],
            ["parsed数据库", str(self.db_path), "结构化分析数据来源"],
            ["parser_version", metadata.get("parser_version") or "-", "online_parse_metadata"],
            ["parser_status", metadata.get("status") or "-", "online_parse_metadata"],
            ["row_counts", metadata.get("row_counts") or "-", "online_parse_metadata"],
        ]

    def fping_sample_rows(self) -> list[list[object]]:
        rows = self._query(
            """
            SELECT COALESCE(NULLIF(local_time, ''), collector_time), device_aligned_time,
                   target_ip, seq, CASE WHEN success THEN '成功' ELSE '超时' END, latency_ms
            FROM fping_samples
            ORDER BY COALESCE(NULLIF(device_aligned_time, ''), collector_time) ASC, seq ASC
            LIMIT ?
            """,
            (self.row_limit,),
        )
        return [list(row) for row in rows]

    def mesh_detail_rows(self) -> list[list[object]]:
        rows = self._query(
            """
            SELECT collector_time, COALESCE(NULLIF(device_time, ''), collector_time), radio, link_state,
                   peer_mac, COALESCE(NULLIF(resolved_peer_name, ''), NULLIF(peer_name, ''), peer_mac),
                   ABS(mr_rssi), belong_station, belong_section, raw_file, raw_line_start
            FROM main_link_samples
            ORDER BY collector_time ASC, id ASC
            LIMIT ?
            """,
            (self.row_limit,),
        )
        output: list[list[object]] = []
        for row in rows:
            values = list(row)
            values[3] = format_link_state(values[3])
            output.append(values)
        return output

    def timeline_metric_rows(self) -> list[list[object]]:
        rows = self.timeline_rows()
        return [[row[0], row[3], row[5], row[6], row[7], row[8]] for row in rows]

    def table_counts(self) -> dict[str, int]:
        if self._counts_cache is not None:
            return self._counts_cache
        tables = [
            "main_link_samples",
            "channel_busy_records",
            "radio_statistics_samples",
            "interface_rate_samples",
            "fping_samples",
            "fping_1s_summary",
            "switch_history_events",
            "switch_realtime_events",
            "active_segments",
            "active_segment_metrics",
            "analysis_events",
            "online_parse_issues",
            "online_parse_metadata",
            "time_sync_samples",
        ]
        counts: dict[str, int] = {}
        if not self.db_path.exists():
            self._counts_cache = {table: 0 for table in tables}
            return self._counts_cache
        with self._connect() as conn:
            for table in tables:
                counts[table] = self._count_table(conn, table)
        self._counts_cache = counts
        return counts

    def basic_stats(self) -> dict[str, object]:
        row = self._one(
            """
            SELECT MIN(collector_time), MAX(collector_time),
                   ROUND(AVG(CASE WHEN UPPER(COALESCE(link_state, '')) LIKE 'ACTIVE%' THEN ABS(mr_rssi) END), 2),
                   MIN(CASE WHEN UPPER(COALESCE(link_state, '')) LIKE 'ACTIVE%' THEN ABS(mr_rssi) END)
            FROM main_link_samples
            """
        )
        if not row or row[2] is None:
            segment_row = self._one(
                """
                SELECT MIN(start_time), MAX(end_time), ROUND(AVG(ABS(avg_mr_rssi)), 2), MIN(ABS(min_mr_rssi))
                FROM active_segments
                """
            )
            if segment_row and segment_row[2] is not None:
                row = segment_row
        ping = self._one("SELECT ROUND(AVG(loss_percent), 2), ROUND(MAX(loss_percent), 2), ROUND(AVG(avg_latency_ms), 2), ROUND(MAX(avg_latency_ms), 2) FROM fping_1s_summary")
        busy = self._one("SELECT ROUND(AVG(tx_busy), 2), MAX(tx_busy), ROUND(AVG(rx_busy), 2), MAX(rx_busy) FROM channel_busy_records")
        return {
            "start_time": row[0] if row else None,
            "end_time": row[1] if row else None,
            "avg_rssi": row[2] if row else None,
            "min_rssi": row[3] if row else None,
            "avg_loss": ping[0] if ping else None,
            "max_loss": ping[1] if ping else None,
            "avg_latency": ping[2] if ping else None,
            "max_latency": ping[3] if ping else None,
            "avg_tx_busy": busy[0] if busy else None,
            "max_tx_busy": busy[1] if busy else None,
            "avg_rx_busy": busy[2] if busy else None,
            "max_rx_busy": busy[3] if busy else None,
        }

    def _derived_anomaly_rows(self) -> list[list[object]]:
        rows: list[list[object]] = []
        for index, row in enumerate(self._query("SELECT COALESCE(NULLIF(device_bucket_time, ''), bucket_time), target_ip, loss_percent FROM fping_1s_summary WHERE COALESCE(loss_percent, 0) >= 20 ORDER BY 1 ASC LIMIT 100"), 1):
            rows.append([f"DL-{index}", row[0], "FPING_HIGH_LOSS", "WARNING", f"{row[1]} 丢包率 {row[2]}%", f"DL-{index}"])
        for index, row in enumerate(self._query("SELECT collector_time, peer_mac, ABS(mr_rssi) FROM main_link_samples WHERE UPPER(COALESCE(link_state, '')) LIKE 'ACTIVE%' AND ABS(mr_rssi) < 25 ORDER BY collector_time ASC LIMIT 100"), 1):
            rows.append([f"DR-{index}", row[0], "WEAK_ACTIVE_RSSI", "WARNING", f"{row[1]} 主链路RSSI {row[2]}", f"DR-{index}"])
        return rows

    def _read_session_meta(self) -> dict[str, object]:
        path = self.session_dir / "session_meta.json"
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _latest_metadata(self) -> dict[str, object]:
        row = self._one("SELECT parser_version, row_counts, status, error_summary FROM online_parse_metadata ORDER BY id DESC LIMIT 1")
        if not row:
            return {}
        return {"parser_version": row[0], "row_counts": row[1], "status": row[2], "error_summary": row[3]}

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _count_table(self, conn: sqlite3.Connection, table: str) -> int:
        if not self.db_path.exists():
            return 0
        try:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.Error:
            return 0

    def _query(self, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        if not self.db_path.exists():
            return []
        try:
            with self._connect() as conn:
                return [tuple(row) for row in conn.execute(sql, params).fetchall()]
        except sqlite3.Error:
            return []

    def _one(self, sql: str, params: tuple[object, ...] = ()) -> tuple[object, ...] | None:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    def _timed_rows(self, sql: str, params: tuple[object, ...]) -> list[tuple[datetime, tuple[object, ...]]]:
        rows: list[tuple[datetime, tuple[object, ...]]] = []
        for row in self._query(sql, params):
            timestamp = _parse_time(row[0])
            if timestamp is not None:
                rows.append((timestamp, row))
        return rows


def _parse_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace("T", " "), text[:19]):
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _nearest_tuple(rows: list[tuple[datetime, tuple[object, ...]]], time_value: object, *, max_seconds: float) -> tuple[object, ...] | None:
    timestamp = _parse_time(time_value)
    if timestamp is None:
        return None
    best: tuple[object, ...] | None = None
    best_delta = max_seconds + 1
    for item_time, row in rows:
        delta = abs((item_time - timestamp).total_seconds())
        if delta <= max_seconds and delta < best_delta:
            best_delta = delta
            best = row
    return best


def _nearest_value(rows: list[tuple[datetime, tuple[object, ...]]], time_value: object, *, max_seconds: float) -> object | None:
    row = _nearest_tuple(rows, time_value, max_seconds=max_seconds)
    return row[1] if row and len(row) > 1 else None


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _score_level(score: float) -> str:
    score = float(score)
    if score >= 85:
        return "良好"
    if score >= 70:
        return "关注"
    if score >= 50:
        return "较差"
    return "异常"


def _score_level_or_na(score: object) -> str:
    if score in (None, "", "N/A"):
        return "数据不足"
    return _score_level(_num(score))


def _timeline_conclusion(rssi: object, loss: object, tx_busy: object, rx_busy: object) -> str:
    if _num(loss) >= 20:
        return "业务丢包明显"
    if _num(rssi) and _num(rssi) < 25:
        return "主链路RSSI偏弱"
    if max(_num(tx_busy), _num(rx_busy)) >= 80:
        return "空口繁忙"
    return "正常"


def _fping_conclusion(loss: object, latency: object) -> str:
    if _num(loss) >= 20:
        return "严重丢包"
    if _num(loss) > 0:
        return "存在丢包"
    if _num(latency) >= 100:
        return "延迟偏高"
    return "正常"


def _segment_conclusion(rssi: object, loss: object, tx_busy: object, rx_busy: object) -> str:
    parts: list[str] = []
    if _num(rssi) and _num(rssi) < 25:
        parts.append("区段RSSI偏弱")
    if _num(loss) > 0:
        parts.append("区段内存在丢包")
    if max(_num(tx_busy), _num(rx_busy)) >= 80:
        parts.append("区段空口繁忙")
    return "；".join(parts) if parts else "正常"


def _peer_conclusion(active_count: object, avg_rssi: object, min_rssi: object) -> str:
    if _num(active_count) <= 0:
        return "仅备链出现"
    if _num(min_rssi) and _num(min_rssi) < 25:
        return "曾出现弱RSSI"
    if _num(avg_rssi) and _num(avg_rssi) < 30:
        return "平均RSSI偏低"
    return "正常"


def _is_switch_impacted(old_rssi: object, new_rssi: object, loss: object | None) -> bool:
    return _num(loss) > 0 or (_num(new_rssi) > 0 and _num(new_rssi) < 25) or (_num(old_rssi) > 0 and _num(old_rssi) < 25)


def _switch_suggestion(old_rssi: object, new_rssi: object, loss: object | None) -> str:
    if _num(loss) > 0:
        return "切换邻近时间出现 fping 丢包，建议结合 RSSI/繁忙度定位。"
    if _num(new_rssi) > 0 and _num(new_rssi) < 25:
        return "切入后 RSSI 偏弱，建议核对 AP 覆盖和切换门限。"
    if _num(old_rssi) > 0 and _num(old_rssi) < 25:
        return "切出前 RSSI 偏弱，属于低信号触发切换的可能性较高。"
    return "未发现明显业务影响。"


def _loss_judgment(loss: object, rssi: object, switch: tuple[object, ...] | None, tx_busy: object, rx_busy: object) -> str:
    reasons: list[str] = []
    if _num(rssi) and _num(rssi) < 25:
        reasons.append("弱RSSI")
    if switch:
        reasons.append("邻近切换")
    if max(_num(tx_busy), _num(rx_busy)) >= 80:
        reasons.append("空口繁忙")
    if not reasons:
        return "丢包原因需结合原始日志继续确认"
    return f"丢包率 {loss}%；关联因素：" + "、".join(reasons)


def _busy_conclusion(ctl_max: object, tx_max: object, rx_max: object) -> str:
    value = max(_num(ctl_max), _num(tx_max), _num(rx_max))
    if value >= 90:
        return "严重繁忙"
    if value >= 80:
        return "繁忙关注"
    return "正常"


def _generic_metric_conclusion(metric: object, maximum: object) -> str:
    if _num(maximum) >= 80 and "busy" in str(metric or "").lower():
        return "繁忙关注"
    return "正常"


def _interface_conclusion(total_max: object, broadcast_max: object, multicast_max: object) -> str:
    if _num(broadcast_max) > 1000 or _num(multicast_max) > 1000:
        return "广播/组播PPS偏高"
    if _num(total_max) > 10000:
        return "接口PPS偏高"
    return "正常"


def _line_range(start: object, end: object) -> object:
    if start in (None, ""):
        return "-"
    if end in (None, "", start):
        return start
    return f"{start}-{end}"


def _num(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
