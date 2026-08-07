// NetConsole WPS_STANDARD_SPREADSHEET AirScript protocol v2.
// Publish this script in the ordinary online spreadsheet document.
// The exact workbook API names are kept in these small helpers so a WPS
// runtime upgrade does not change the NetConsole payload contract.
const PROTOCOL_VERSION = 2;
const SCRIPT_VERSION = "2.3.0-standard";
const DEPLOYMENT_ID = "trackside-ap-standard-2.3.0";
const DOCUMENT_ID = "549847228994";
const TARGET_TYPE = "WPS_STANDARD_SPREADSHEET";
const TARGET_CODE = "wps_standard_spreadsheet";
const RUNTIME_CAPABILITY = "VERIFIED";
const META_SHEET = "_NetConsoleSyncMeta";
const PROBE_SHEET = "_NetConsoleRuntimeProbe";

function argv() {
  const value = (typeof Context !== "undefined" && Context.argv) || {};
  return value.Context && value.Context.argv ? value.Context.argv : value;
}

function response(value) {
  const contextValue = (typeof Context !== "undefined" && Context.argv) || {};
  const context = contextValue.Context && contextValue.Context.argv ? contextValue.Context.argv : contextValue;
  return JSON.stringify({ protocol_version: PROTOCOL_VERSION, script_version: SCRIPT_VERSION, deployment_id: DEPLOYMENT_ID, document_id: DOCUMENT_ID, target_type: TARGET_TYPE, target_code: TARGET_CODE, script_id: String(context.script_id || context.expected_script_id || ""), runtime_capability: RUNTIME_CAPABILITY, ...value });
}

function worksheets() {
  if (typeof Application === "undefined") throw new Error("WPS Application API unavailable");
  if (!Application.Worksheets) throw new Error("WPS Application.Worksheets API unavailable");
  return Application.Worksheets;
}

function sheetNames() {
  const sheets = worksheets();
  const result = [];
  for (let index = 0; index < sheets.Count; index += 1) result.push(String(sheets.Item(index + 1).Name || ""));
  return result;
}

function connectionTest() {
  // This operation is deliberately read-only: it never creates a binding.
  const meta = readBinding();
  return response({ success: true, binding_status: meta ? "BOUND" : "UNBOUND", ...(meta || {}), objects: [], capabilities: { supports_sheets: true, supports_tables: false, supports_records: false, supports_insert_rows: true, supports_batch_write: true, max_payload_bytes: 20 * 1024 * 1024, max_rows_per_request: 5000 }, verification: "CONNECTION_PROBE_ONLY" });
}

function ensureSheet(name) {
  const sheets = worksheets();
  for (let index = 0; index < sheets.Count; index += 1) if (String(sheets.Item(index + 1).Name) === name) return sheets.Item(index + 1);
  const sheet = sheets.Add();
  if (sheet && "Name" in sheet) sheet.Name = name;
  return sheet;
}

function findSheet(name) {
  const sheets = worksheets();
  for (let index = 0; index < sheets.Count; index += 1) {
    const sheet = sheets.Item(index + 1);
    if (String(sheet.Name || "") === name) return sheet;
  }
  return null;
}

function readBinding() {
  const sheet = findSheet(META_SHEET);
  if (!sheet) return null;
  const values = sheet.Range("A1:B20").Value2;
  const meta = {};
  for (const row of values || []) if (row && row[0]) meta[String(row[0])] = row[1];
  return meta.binding_id ? meta : null;
}

function writeBinding(args) {
  const sheet = ensureSheet(META_SHEET);
  const values = [
    ["document_id", DOCUMENT_ID], ["binding_id", args.binding_id],
    ["site_id", args.site_id], ["site_name", args.site_name],
    ["business_key", args.business_key], ["target_code", TARGET_CODE],
    ["target_type", TARGET_TYPE], ["protocol_version", PROTOCOL_VERSION],
    ["script_version", SCRIPT_VERSION], ["deployment_id", DEPLOYMENT_ID],
    ["first_bound_at", new Date().toISOString()], ["last_sync_at", ""],
    ["last_sync_revision", ""], ["last_target_batch_id", ""],
  ];
  sheet.Range("A1").Resize(values.length, 2).Value2 = values;
  if ("Visible" in sheet) sheet.Visible = false;
  return Object.fromEntries(values);
}

function assertBinding(args) {
  let meta = readBinding();
  if (!meta) {
    if (!args.initialize_binding) return { ok: false, error: response({ success: false, error_code: "WPS_DOCUMENT_UNBOUND", message: "当前文档尚未绑定，必须显式确认后才能写入", binding_status: "UNBOUND" }) };
    meta = writeBinding(args);
  }
  for (const key of ["document_id", "binding_id", "site_id", "business_key", "target_code", "target_type"]) {
    const expected = key === "document_id" ? DOCUMENT_ID : key === "target_code" ? TARGET_CODE : key === "target_type" ? TARGET_TYPE : args[key];
    if (String(meta[key] || "") !== String(expected || "")) {
      return { ok: false, error: response({ success: false, error_code: "WPS_DOCUMENT_BINDING_MISMATCH", message: "远端文档绑定与当前请求不一致", binding_status: "MISMATCH", ...meta }) };
    }
  }
  return { ok: true, meta };
}

function addFormatWarning(warnings, sheetName, feature, error) {
  const reason = String(error && error.message || error || "unsupported").slice(0, 300);
  const key = `${sheetName}|${feature}|${reason}`;
  if (warnings.some((item) => item.key === key) || warnings.length >= 100) return;
  warnings.push({ key, sheet_name: sheetName, feature, reason });
}

function attemptFormat(warnings, sheetName, feature, action) {
  try {
    action();
    return true;
  } catch (error) {
    addFormatWarning(warnings, sheetName, feature, error);
    return false;
  }
}

function enumValue(group, name, fallback) {
  const enums = Application && Application.Enum;
  return enums && enums[group] && enums[group][name] !== undefined ? enums[group][name] : fallback;
}

function horizontalAlignment(value) {
  const names = {
    center: ["xlHAlignCenter", -4108],
    centerContinuous: ["xlHAlignCenterAcrossSelection", 7],
    distributed: ["xlHAlignDistributed", -4117],
    fill: ["xlHAlignFill", 5],
    general: ["xlHAlignGeneral", 1],
    justify: ["xlHAlignJustify", -4130],
    left: ["xlHAlignLeft", -4131],
    right: ["xlHAlignRight", -4152],
  };
  const entry = names[String(value || "")];
  return entry ? enumValue("XlHAlign", entry[0], entry[1]) : null;
}

function verticalAlignment(value) {
  const names = {
    bottom: ["xlVAlignBottom", -4107],
    center: ["xlVAlignCenter", -4108],
    distributed: ["xlVAlignDistributed", -4117],
    justify: ["xlVAlignJustify", -4130],
    top: ["xlVAlignTop", -4160],
  };
  const entry = names[String(value || "")];
  return entry ? enumValue("XlVAlign", entry[0], entry[1]) : null;
}

function borderDefinition(style) {
  const normalized = String(style || "");
  const dashed = {
    dash: ["xlDash", -4115], dot: ["xlDot", -4118], dashDot: ["xlDashDot", 4],
    dashDotDot: ["xlDashDotDot", 5], slantDashDot: ["xlSlantDashDot", 13],
  };
  const compact = normalized.replace(/^medium/, "");
  const dash = dashed[compact.charAt(0).toLowerCase() + compact.slice(1)];
  const lineStyle = dash
    ? enumValue("XlLineStyle", dash[0], dash[1])
    : normalized === "double"
      ? enumValue("XlLineStyle", "xlDouble", -4119)
      : enumValue("XlLineStyle", "xlContinuous", 1);
  const weight = normalized === "hair"
    ? enumValue("XlBorderWeight", "xlHairline", 1)
    : normalized === "thick"
      ? enumValue("XlBorderWeight", "xlThick", 4)
      : normalized.startsWith("medium")
        ? enumValue("XlBorderWeight", "xlMedium", -4138)
        : enumValue("XlBorderWeight", "xlThin", 2);
  return { lineStyle, weight };
}

function applyBorder(range, sideName, definition) {
  const borderNames = {
    left: ["xlEdgeLeft", 7], top: ["xlEdgeTop", 8], bottom: ["xlEdgeBottom", 9],
    right: ["xlEdgeRight", 10], diagonalDown: ["xlDiagonalDown", 5], diagonalUp: ["xlDiagonalUp", 6],
  };
  const entry = borderNames[sideName];
  if (!entry || !definition || !definition.style) return;
  const border = range.Borders.Item(enumValue("XlBordersIndex", entry[0], entry[1]));
  const style = borderDefinition(definition.style);
  border.LineStyle = style.lineStyle;
  border.Weight = style.weight;
  if (definition.color) border.Color = definition.color;
}

function applyFormatRun(sheet, run, warnings) {
  if (!run || !run.range) return;
  let range = null;
  const rangeReady = attemptFormat(warnings, sheet.Name, "format_range", () => { range = sheet.Range(run.range); });
  if (!rangeReady || !range) return;
  const font = run.font || {};
  if (font.name) attemptFormat(warnings, sheet.Name, "font_name", () => { range.Font.Name = font.name; });
  if (font.size) attemptFormat(warnings, sheet.Name, "font_size", () => { range.Font.Size = font.size; });
  if ("bold" in font) attemptFormat(warnings, sheet.Name, "font_bold", () => { range.Font.Bold = !!font.bold; });
  if ("italic" in font) attemptFormat(warnings, sheet.Name, "font_italic", () => { range.Font.Italic = !!font.italic; });
  if ("strike" in font) attemptFormat(warnings, sheet.Name, "font_strike", () => { range.Font.Strikethrough = !!font.strike; });
  if (font.color) attemptFormat(warnings, sheet.Name, "font_color", () => { range.Font.Color = font.color; });
  if (font.underline) {
    const underline = font.underline === "double"
      ? enumValue("XlUnderlineStyle", "xlUnderlineStyleDouble", -4119)
      : enumValue("XlUnderlineStyle", "xlUnderlineStyleSingle", 2);
    attemptFormat(warnings, sheet.Name, "font_underline", () => { range.Font.Underline = underline; });
  }
  const fill = run.fill || {};
  if (fill.fg_color) attemptFormat(warnings, sheet.Name, "fill", () => { range.Interior.Color = fill.fg_color; });
  if (run.number_format) attemptFormat(warnings, sheet.Name, "number_format", () => { range.NumberFormat = run.number_format; });
  const alignment = run.alignment || {};
  const horizontal = horizontalAlignment(alignment.horizontal);
  const vertical = verticalAlignment(alignment.vertical);
  if (horizontal !== null) attemptFormat(warnings, sheet.Name, "horizontal_alignment", () => { range.HorizontalAlignment = horizontal; });
  if (vertical !== null) attemptFormat(warnings, sheet.Name, "vertical_alignment", () => { range.VerticalAlignment = vertical; });
  if ("wrap_text" in alignment) attemptFormat(warnings, sheet.Name, "wrap_text", () => { range.WrapText = !!alignment.wrap_text; });
  if (alignment.text_rotation) attemptFormat(warnings, sheet.Name, "text_rotation", () => { range.Orientation = alignment.text_rotation; });
  if ("shrink_to_fit" in alignment) attemptFormat(warnings, sheet.Name, "shrink_to_fit", () => { range.ShrinkToFit = !!alignment.shrink_to_fit; });
  const borders = run.border || {};
  for (const sideName of ["left", "top", "bottom", "right"]) {
    if (borders[sideName]) attemptFormat(warnings, sheet.Name, `border_${sideName}`, () => applyBorder(range, sideName, borders[sideName]));
  }
  if (borders.diagonal && borders.diagonal.down) attemptFormat(warnings, sheet.Name, "border_diagonal_down", () => applyBorder(range, "diagonalDown", borders.diagonal));
  if (borders.diagonal && borders.diagonal.up) attemptFormat(warnings, sheet.Name, "border_diagonal_up", () => applyBorder(range, "diagonalUp", borders.diagonal));
}

function clearFullReplaceSheet(sheet, warnings) {
  const used = sheet.UsedRange;
  if (!used) return;
  attemptFormat(warnings, sheet.Name, "clear_merges", () => { used.UnMerge(); });
  const cleared = attemptFormat(warnings, sheet.Name, "clear_values_and_formats", () => { used.Clear(); });
  if (!cleared && used.ClearContents) used.ClearContents();
}

function clearAppendBlock(sheet, rowCount, columnCount, warnings) {
  if (!rowCount || !columnCount) return;
  const range = sheet.Range("A1").Resize(rowCount, columnCount);
  attemptFormat(warnings, sheet.Name, "append_clear_merges", () => { range.UnMerge(); });
  attemptFormat(warnings, sheet.Name, "append_clear_values_and_formats", () => { range.Clear(); });
}

function applyFreezePanes(sheet, address, warnings) {
  if (!address) return;
  attemptFormat(warnings, sheet.Name, "freeze_panes", () => {
    const match = String(address).match(/^([A-Z]+)(\d+)$/);
    if (!match || !Application.ActiveWindow) throw new Error("freeze panes API unavailable");
    let column = 0;
    for (const character of match[1]) column = column * 26 + character.charCodeAt(0) - 64;
    sheet.Activate();
    Application.ActiveWindow.FreezePanes = false;
    Application.ActiveWindow.SplitRow = Math.max(Number(match[2]) - 1, 0);
    Application.ActiveWindow.SplitColumn = Math.max(column - 1, 0);
    Application.ActiveWindow.FreezePanes = true;
  });
}

function verifyKeyFormatting(sheet, sheetDto, warnings) {
  const run = (sheetDto.format_runs || [])[0];
  if (!run) return { checked: false };
  const result = { checked: true, range: run.range };
  attemptFormat(warnings, sheet.Name, "format_readback", () => {
    const range = sheet.Range(run.range);
    if (run.font && "bold" in run.font) result.font_bold = !!range.Font.Bold === !!run.font.bold;
    if (run.number_format) result.number_format = String(range.NumberFormat || "") === String(run.number_format);
    if (run.alignment && "wrap_text" in run.alignment) result.wrap_text = !!range.WrapText === !!run.alignment.wrap_text;
    if (run.fill && run.fill.fg_color) result.fill_readable = range.Interior.Color !== undefined;
  });
  return result;
}

function applySheetFormatting(sheet, sheetDto, warnings) {
  for (const merge of sheetDto.merges || []) attemptFormat(warnings, sheet.Name, "merge", () => { sheet.Range(merge).Merge(); });
  for (const [row, height] of Object.entries(sheetDto.row_heights || {})) {
    attemptFormat(warnings, sheet.Name, "row_height", () => { sheet.Range(`${row}:${row}`).RowHeight = height; });
  }
  for (const [column, width] of Object.entries(sheetDto.column_widths || {})) {
    attemptFormat(warnings, sheet.Name, "column_width", () => { sheet.Range(`${column}:${column}`).ColumnWidth = width; });
  }
  for (const run of sheetDto.format_runs || []) applyFormatRun(sheet, run, warnings);
  applyFreezePanes(sheet, sheetDto.freeze_panes, warnings);
  if (sheetDto.tab_color) attemptFormat(warnings, sheet.Name, "tab_color", () => { sheet.Tab.Color = sheetDto.tab_color; });
  attemptFormat(warnings, sheet.Name, "sheet_visibility", () => { sheet.Visible = sheetDto.sheet_visible !== false; });
  return verifyKeyFormatting(sheet, sheetDto, warnings);
}

function writeSheet(sheetDto, warnings) {
  const sheet = ensureSheet(sheetDto.sheet_name);
  const values = sheetDto.cells || [];
  if (sheetDto.sync_mode === "APPEND_SNAPSHOT") {
    if (values.length) sheet.Range(`A1:A${values.length}`).EntireRow.Insert();
    clearAppendBlock(sheet, values.length, sheetDto.column_count, warnings);
    if (values.length) sheet.Range("A1").Resize(values.length, sheetDto.column_count).Value2 = values;
  } else if (sheetDto.sync_mode === "FULL_REPLACE") {
    clearFullReplaceSheet(sheet, warnings);
    if (values.length) sheet.Range("A1").Resize(values.length, sheetDto.column_count).Value2 = values;
  }
  return { written_rows: values.length, format_verification: applySheetFormatting(sheet, sheetDto, warnings) };
}

function reorderSheets(sheetDtos, warnings) {
  const ordered = [...sheetDtos].sort((left, right) => Number(left.sheet_order || 0) - Number(right.sheet_order || 0));
  for (let index = ordered.length - 1; index >= 0; index -= 1) {
    const sheet = findSheet(ordered[index].sheet_name);
    if (!sheet) continue;
    const first = worksheets().Item(1);
    if (String(first.Name || "") !== String(sheet.Name || "")) {
      attemptFormat(warnings, sheet.Name, "sheet_order", () => { sheet.Move({ Before: first.Id, After: null }); });
    }
  }
  const systemNames = sheetNames().filter((name) => name.startsWith("_NetConsole"));
  for (const name of systemNames) {
    const sheet = findSheet(name);
    if (!sheet) continue;
    attemptFormat(warnings, name, "system_sheet_visibility", () => { sheet.Visible = false; });
    const last = worksheets().Item(worksheets().Count);
    if (String(last.Name || "") !== name) {
      attemptFormat(warnings, name, "system_sheet_order", () => { sheet.Move({ Before: null, After: last.Id }); });
    }
  }
}

function sync(payload) {
  const args = payload;
  if (args.protocol_version !== PROTOCOL_VERSION || args.target_type !== TARGET_TYPE) return response({ success: false, error_code: "WPS_PROTOCOL_MISMATCH", message: "protocol or target type mismatch" });
  const binding = assertBinding(args);
  if (!binding.ok) return binding.error;
  const sheets = args.workbook && args.workbook.sheets ? args.workbook.sheets : [];
  let writtenRows = 0;
  let writtenSheets = 0;
  const formatWarnings = [];
  const sheetResults = [];
  try {
    for (const sheet of sheets) {
      const result = writeSheet(sheet, formatWarnings);
      writtenRows += result.written_rows;
      writtenSheets += 1;
      sheetResults.push({ sheet_name: sheet.sheet_name, sync_mode: sheet.sync_mode, success: true, written_rows: result.written_rows, format_verification: result.format_verification });
    }
    reorderSheets(sheets, formatWarnings);
  } catch (error) {
    return response({ success: false, error_code: "WPS_SHEET_WRITE_FAILED", failed_sheet: sheets[writtenSheets] && sheets[writtenSheets].sheet_name || "", failed_operation: "WRITE_VALUES", written_sheet_count: writtenSheets, written_row_count: writtenRows, message: String(error && error.message || error).slice(0, 500), runtime_error_name: String(error && error.name || "Error"), runtime_error_stack: String(error && error.stack || "").slice(0, 2048), binding_status: "BOUND" });
  }
  const publicWarnings = formatWarnings.map(({ key, ...warning }) => warning);
  return response({ success: true, status: publicWarnings.length ? "SUCCESS_WITH_WARNINGS" : "SUCCESS", binding_status: "BOUND", binding_id: args.binding_id, parent_batch_id: args.parent_batch_id, target_batch_id: args.target_batch_id, site_id: args.site_id, site_name: args.site_name, business_key: args.business_key, snapshot_revision: args.snapshot_revision, snapshot_sha256: args.snapshot_sha256, written_sheet_count: writtenSheets, written_row_count: writtenRows, written_object_count: sheets.length, format_warning_count: publicWarnings.length, format_warnings: publicWarnings, sheets: sheetResults });
}

function runtimeWriteProbe(args) {
  const sheet = ensureSheet(PROBE_SHEET);
  try {
    if (sheet.UsedRange && sheet.UsedRange.ClearContents) sheet.UsedRange.ClearContents();
    const scalarRange = sheet.Range("A1");
    scalarRange.Value2 = "NetConsole runtime probe";
    const scalarPassed = String(scalarRange.Value2 || "") === "NetConsole runtime probe";
    const values = [["probe_id", String(args.probe_id || "")], [new Date().toISOString(), "2x2"]];
    sheet.Range("A2").Resize(2, 2).Value2 = values;
    const echoed = sheet.Range("A2").Resize(2, 2).Value2;
    const matrixPassed = JSON.stringify(echoed) === JSON.stringify(values);
    const capabilities = { worksheet_enum: true, worksheet_item: true, worksheet_create: true, scalar_value2: scalarPassed, matrix_value2: matrixPassed, used_range: !!sheet.UsedRange, clear_contents: true, entire_row_insert: false, visible: true };
    sheet.Range("A4").Resize(1, 1).EntireRow.Insert();
    capabilities.entire_row_insert = true;
    if ("Visible" in sheet) {
      sheet.Visible = false;
      capabilities.visible = sheet.Visible === false;
    }
    if (sheet.UsedRange && sheet.UsedRange.ClearContents) sheet.UsedRange.ClearContents();
    const passed = Object.values(capabilities).every(Boolean);
    return response({ success: passed, error_code: passed ? "" : "WPS_RUNTIME_PROBE_VERIFY_FAILED", message: passed ? "运行时能力探针通过" : "运行时能力探针未通过", binding_status: readBinding() ? "BOUND" : "UNBOUND", runtime_capability: passed ? "VERIFIED" : "DEPLOYMENT_PENDING", capabilities: capabilities, probe_sheet: PROBE_SHEET, probe_id: args.probe_id });
  } catch (error) {
    return response({ success: false, error_code: "WPS_RUNTIME_PROBE_FAILED", message: String(error && error.message || error).slice(0, 500), runtime_error_name: String(error && error.name || "Error"), runtime_error_stack: String(error && error.stack || "").slice(0, 2048), binding_status: readBinding() ? "BOUND" : "UNBOUND", runtime_capability: "DEPLOYMENT_PENDING" });
  }
}

function syncTestSheet(args) {
  const sheet = ensureSheet("_NetConsoleSyncTest");
  const values = [["operation", "probe_id", "status"], ["sync_test_sheet", String(args.probe_id || ""), "OK"]];
  try {
    sheet.Range("A1").Resize(2, 3).Value2 = values;
    const echoed = sheet.Range("A1").Resize(2, 3).Value2;
    const passed = JSON.stringify(echoed) === JSON.stringify(values);
    if (sheet.UsedRange && sheet.UsedRange.ClearContents) sheet.UsedRange.ClearContents();
    if ("Visible" in sheet) sheet.Visible = false;
    return response({ success: passed, error_code: passed ? "" : "WPS_SYNC_TEST_VERIFY_FAILED", message: passed ? "同步测试 Sheet 通过" : "同步测试 Sheet 写后读取不一致", binding_status: readBinding() ? "BOUND" : "UNBOUND", runtime_capability: passed ? "VERIFIED" : "DEPLOYMENT_PENDING", probe_sheet: "_NetConsoleSyncTest", probe_id: args.probe_id });
  } catch (error) {
    return response({ success: false, error_code: "WPS_SYNC_TEST_FAILED", message: String(error && error.message || error).slice(0, 500), runtime_error_name: String(error && error.name || "Error"), runtime_error_stack: String(error && error.stack || "").slice(0, 2048), binding_status: readBinding() ? "BOUND" : "UNBOUND", runtime_capability: "DEPLOYMENT_PENDING", probe_sheet: "_NetConsoleSyncTest", probe_id: args.probe_id });
  }
}

function main() {
  const args = argv();
  if (args.operation === "connection_test") return connectionTest();
  if (args.operation === "runtime_write_probe") return runtimeWriteProbe(args);
  if (args.operation === "sync_test_sheet") return syncTestSheet(args);
  if (args.operation === "sync_trackside_ap_business") return sync(args);
  return response({ success: false, error_code: "OPERATION_UNSUPPORTED", message: "unsupported operation" });
}

// Explicit execution entry point. Confirm the returned JSON in the WPS editor
// before using the newly copied webhook in production.
return main();
