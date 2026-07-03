from __future__ import annotations

import sqlite3
from pathlib import Path

from netconsole.services.online_mr_chart_builder import OnlineMrChartBuilder, ChartData


class OnlineMrAnalysisReportExporter:
    def export(self, session_dir: Path, output_path: Path) -> Path:
        from openpyxl import Workbook
        from openpyxl.chart import BarChart, LineChart, Reference
        from openpyxl.styles import Alignment, Font, PatternFill

        session_dir = Path(session_dir)
        output_path = Path(output_path)
        db_path = session_dir / "parsed" / "online_diagnosis.sqlite"
        builder = OnlineMrChartBuilder(db_path)
        workbook = Workbook()
        overview = workbook.active
        overview.title = "综合结论"
        self._write_overview(overview, db_path)
        self._append_offline_report_sheets(workbook, session_dir, db_path)

        chart_specs = [
            ("主链路信号趋势表", "主链路信号趋势图", builder.build_active_rssi_series(), LineChart),
            ("主链路切换前后信号趋势表", "主链路切换前后信号趋势图", builder.build_switch_rssi_series(), LineChart),
            ("信道繁忙度趋势表", "信道繁忙度趋势图", builder.build_channel_busy_series(), LineChart),
            ("Ping丢包率趋势表", "Ping丢包率趋势图", builder.build_ping_loss_series(), LineChart),
            ("Ping延迟趋势表", "Ping延迟趋势图", builder.build_ping_latency_series(), LineChart),
            ("接口PPS趋势表", "接口PPS趋势图", builder.build_interface_rate_series(), LineChart),
            ("主链路切换原因统计表", "主链路切换原因统计图", builder.build_switch_reason_summary(), BarChart),
        ]
        for data_sheet_name, chart_sheet_name, chart_data, chart_type in chart_specs:
            data_sheet = workbook.create_sheet(data_sheet_name)
            self._write_chart_data(data_sheet, chart_data)
            chart_sheet = workbook.create_sheet(chart_sheet_name)
            self._write_chart_sheet(chart_sheet, data_sheet, chart_data, chart_type, chart_sheet_name)

        for sheet in workbook.worksheets:
            sheet.freeze_panes = "A2"
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1F4E79")
                cell.alignment = Alignment(horizontal="center")
            for column in sheet.columns:
                letter = column[0].column_letter
                sheet.column_dimensions[letter].width = min(max(max(len(str(cell.value or "")) for cell in column) + 2, 12), 36)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(output_path)
        return output_path

    def _append_offline_report_sheets(self, workbook, session_dir: Path, db_path: Path) -> None:
        sheet_rows = {
            "会话信息": self._session_info_rows(session_dir, db_path),
            "质量总览": [["维度", "结论", "说明"], ["业务连通性", "N/A", "缺少 fping 数据时不按 0 计算"], ["Mesh主链路", "N/A", "基于 parsed 数据计算"], ["空口繁忙度", "N/A", "无数据时显示 N/A"]],
            "时间轴质量分析": [["时间", "Active Peer", "MR侧RSSI", "TxBusy", "RxBusy", "fping丢包率", "平均延迟", "质量等级", "原因"]],
            "fping业务质量": [["时间", "目标IP", "发送", "接收", "丢包", "丢包率", "平均延迟", "最大延迟", "抖动"]],
            "Mesh主链路质量": [["时间", "射频ID", "链路状态", "对端名称", "对端MAC", "MR侧RSSI", "归属站点"]],
            "Peer稳定性分析": [["Peer", "Active次数", "平均RSSI", "最低RSSI", "切换次数", "结论"]],
            "切换影响分析": [["切换时间", "原Peer", "新Peer", "切换前RSSI", "切换后RSSI", "切换原因", "是否影响业务", "建议"]],
            "丢包关联分析": [["丢包时间", "丢包率", "Active RSSI", "是否切换", "TxBusy", "RxBusy", "判断"]],
            "异常事件清单": [["事件ID", "事件时间", "事件类型", "级别", "说明", "证据ID"]],
            "空口繁忙度分析": [["时间", "射频ID", "CtlBusy", "TxBusy", "RxBusy", "结论"]],
            "射频统计分析": [["时间", "指标", "当前值", "增量", "结论"]],
            "接口速率分析": [["时间", "方向", "接口", "总PPS", "广播PPS", "组播PPS", "说明"]],
            "链路重建与连接异常": [["时间", "Peer", "事件", "RSSI", "原因", "证据ID"]],
            "原始证据片段": [["证据ID", "来源Sheet", "事件类型", "采样时间", "源文件", "源行号", "原始日志片段"]],
            "参数配置": [["配置项", "值"], ["规则来源", "resources/mesh_quality_rules.json"], ["报告类型", "VEHICLE_MR_REALTIME_OFFLINE"]],
        }
        for name, rows in sheet_rows.items():
            sheet = workbook.create_sheet(name)
            for row in rows:
                sheet.append(["N/A" if value is None else value for value in row])

    def _session_info_rows(self, session_dir: Path, db_path: Path) -> list[list[object]]:
        meta_path = session_dir / "session_meta.json"
        rows: list[list[object]] = [["字段", "值"]]
        if meta_path.exists():
            import json

            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
            for key in ("session_id", "mr_name", "device_name", "host", "started_at", "ended_at", "status"):
                rows.append([key, meta.get(key) or "N/A"])
        if db_path.exists():
            with sqlite3.connect(db_path) as conn:
                table_counts = []
                for table in ("live_samples", "live_mesh_links", "live_channel_busy", "live_active_link_switch_logs", "ping_samples", "live_interface_rates"):
                    try:
                        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    except sqlite3.Error:
                        count = "N/A"
                    table_counts.append([table, count])
            rows.append(["parsed_db", str(db_path)])
            rows.extend(table_counts)
        return rows

    def _write_overview(self, sheet, db_path: Path) -> None:
        stats = {
            "设备数量": 0,
            "主链路切换次数": 0,
            "空链路次数": 0,
            "平均RSSI": None,
            "最低RSSI": None,
            "平均信道繁忙度": None,
            "Ping平均丢包率": None,
            "Ping平均延迟": None,
        }
        if db_path.exists():
            with sqlite3.connect(db_path) as conn:
                stats["主链路切换次数"] = conn.execute("SELECT COUNT(*) FROM live_active_link_switch_logs").fetchone()[0]
                stats["空链路次数"] = conn.execute("SELECT COUNT(*) FROM live_active_link_switch_logs WHERE from_resolve_rule = 'empty_link' OR to_resolve_rule = 'empty_link'").fetchone()[0]
                rssi = conn.execute("SELECT AVG(local_rssi_db), MIN(local_rssi_db) FROM live_mesh_links WHERE UPPER(link_state) LIKE 'ACTIVE%' AND local_rssi_db IS NOT NULL").fetchone()
                stats["平均RSSI"], stats["最低RSSI"] = rssi
                busy = conn.execute("SELECT AVG(tx_busy), AVG(rx_busy) FROM live_channel_busy").fetchone()
                if busy and busy[0] is not None and busy[1] is not None:
                    stats["平均信道繁忙度"] = round((float(busy[0]) + float(busy[1])) / 2, 2)
                ping = conn.execute("SELECT AVG(CASE WHEN success = 1 THEN 0 ELSE 100 END), AVG(latency_ms) FROM ping_samples").fetchone()
                stats["Ping平均丢包率"], stats["Ping平均延迟"] = ping
        sheet.append(["指标", "值"])
        for key, value in stats.items():
            sheet.append([key, "" if value is None else value])

    def _write_chart_data(self, sheet, chart_data: ChartData) -> None:
        headers = ["时间/类别"] + [series.name for series in chart_data.series]
        sheet.append(headers)
        x_values: list[object] = []
        for series in chart_data.series:
            for x_value, _y_value in series.points:
                if x_value not in x_values:
                    x_values.append(x_value)
        values_by_series = [{x: y for x, y in series.points} for series in chart_data.series]
        for x_value in x_values:
            sheet.append([x_value] + [values.get(x_value) for values in values_by_series])

    def _write_chart_sheet(self, sheet, data_sheet, chart_data: ChartData, chart_type, title: str) -> None:
        from openpyxl.chart import Reference
        from openpyxl.styles import Font

        sheet["A1"] = title
        sheet["A1"].font = Font(bold=True, size=14)
        if data_sheet.max_row < 2 or data_sheet.max_column < 2:
            sheet["A3"] = chart_data.empty_message
            return
        chart = chart_type()
        chart.title = title
        chart.y_axis.title = chart_data.y_label
        data = Reference(data_sheet, min_col=2, max_col=data_sheet.max_column, min_row=1, max_row=data_sheet.max_row)
        categories = Reference(data_sheet, min_col=1, min_row=2, max_row=data_sheet.max_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(categories)
        chart.height = 14
        chart.width = 28
        sheet.add_chart(chart, "A3")
