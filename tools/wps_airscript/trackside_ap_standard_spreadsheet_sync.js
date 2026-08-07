// NetConsole WPS_STANDARD_SPREADSHEET AirScript protocol v2.
// Publish this script in the ordinary online spreadsheet document.
// The exact workbook API names are kept in these small helpers so a WPS
// runtime upgrade does not change the NetConsole payload contract.
const PROTOCOL_VERSION = 2;
const SCRIPT_VERSION = "2.4.0-standard";
const DEPLOYMENT_ID = "trackside-ap-standard-2.4.0";
const DOCUMENT_ID = "549847228994";
const TARGET_TYPE = "WPS_STANDARD_SPREADSHEET";
const TARGET_CODE = "wps_standard_spreadsheet";
const RUNTIME_CAPABILITY = "VERIFIED";
const META_SHEET = "_NetConsoleSyncMeta";
const PROBE_SHEET = "_NetConsoleRuntimeProbe";
const FORMAT_MIRROR_EXPERIMENTAL = false;

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

function isLegacyBindingId(value) {
  return /^wst_[0-9a-f]{32}$/i.test(String(value || ""));
}

function requestedBindingId(args) {
  return String(args.new_binding_id || args.binding_id || "");
}

function bindingDiagnostics(args, existingMeta) {
  const meta = existingMeta === undefined ? readBinding() : existingMeta;
  const remoteBindingId = String(meta && meta.binding_id || "");
  const remoteDocumentId = String(meta && meta.document_id || "");
  const remoteSiteId = String(meta && meta.site_id || "");
  const remoteSiteName = String(meta && meta.site_name || "");
  const remoteBusinessKey = String(meta && meta.business_key || "");
  const remoteTargetCode = String(meta && meta.target_code || "");
  const remoteTargetType = String(meta && meta.target_type || "");
  const expectedDocumentId = String(args.document_id || DOCUMENT_ID);
  const expectedTargetCode = String(args.target_code || TARGET_CODE);
  const expectedTargetType = String(args.target_type || TARGET_TYPE);
  const documentMatch = Boolean(remoteDocumentId) && expectedDocumentId === DOCUMENT_ID && remoteDocumentId === expectedDocumentId;
  const siteMatch = Boolean(remoteSiteId) && remoteSiteId === String(args.site_id || "");
  const businessMatch = Boolean(remoteBusinessKey) && remoteBusinessKey === String(args.business_key || "");
  const targetCodeMatch = Boolean(remoteTargetCode) && expectedTargetCode === TARGET_CODE && remoteTargetCode === expectedTargetCode;
  const targetTypeMatch = Boolean(remoteTargetType) && expectedTargetType === TARGET_TYPE && remoteTargetType === expectedTargetType;
  const bindingIdMatch = Boolean(remoteBindingId) && remoteBindingId === requestedBindingId(args);
  const businessIdentityMatches = documentMatch && siteMatch && businessMatch && targetCodeMatch && targetTypeMatch;
  let bindingStatus = "UNBOUND";
  if (remoteBindingId && businessIdentityMatches && bindingIdMatch) bindingStatus = "BOUND";
  else if (remoteBindingId && businessIdentityMatches && isLegacyBindingId(remoteBindingId)) bindingStatus = "LEGACY_BINDING_ID_MISMATCH";
  else if (remoteBindingId) bindingStatus = "MISMATCH";
  return {
    binding_status: bindingStatus,
    local_binding_id: requestedBindingId(args),
    remote_binding_id: remoteBindingId,
    binding_id_match: bindingIdMatch,
    remote_document_id: remoteDocumentId,
    remote_site_id: remoteSiteId,
    remote_site_name: remoteSiteName,
    remote_business_key: remoteBusinessKey,
    remote_target_code: remoteTargetCode,
    remote_target_type: remoteTargetType,
    document_match: documentMatch,
    document_identity_match: documentMatch,
    site_match: siteMatch,
    site_identity_match: siteMatch,
    business_match: businessMatch,
    business_identity_match: businessMatch,
    target_code_match: targetCodeMatch,
    target_type_match: targetTypeMatch,
    target_match: targetCodeMatch && targetTypeMatch,
  };
}

function connectionTest(args) {
  // This operation is deliberately read-only: it never creates a binding.
  return response({ success: true, ...bindingDiagnostics(args), objects: [], capabilities: { supports_sheets: true, supports_tables: false, supports_records: false, supports_insert_rows: true, supports_batch_write: true, max_payload_bytes: 20 * 1024 * 1024, max_rows_per_request: 5000 }, verification: "CONNECTION_PROBE_ONLY" });
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
  const values = sheet.Range("A1:B30").Value2;
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
    ["last_prepend_target_batch_id", ""],
  ];
  sheet.Range("A1").Resize(values.length, 2).Value2 = values;
  if ("Visible" in sheet) sheet.Visible = false;
  return Object.fromEntries(values);
}

function updateBindingMetadata(values) {
  const sheet = findSheet(META_SHEET);
  if (!sheet) throw new Error("binding metadata sheet not found");
  const rows = sheet.Range("A1:B30").Value2 || [];
  const positions = {};
  for (let index = 0; index < rows.length; index += 1) {
    const key = String(rows[index] && rows[index][0] || "");
    if (key) positions[key] = index + 1;
  }
  let nextRow = Math.max(
    1,
    ...Object.values(positions).map((value) => Number(value) + 1),
  );
  for (const [key, value] of Object.entries(values || {})) {
    const row = positions[key] || nextRow++;
    if (!positions[key]) sheet.Range(`A${row}`).Value2 = key;
    sheet.Range(`B${row}`).Value2 = value;
  }
  return readBinding();
}

function assertBinding(args) {
  let meta = readBinding();
  if (!meta) {
    if (!args.initialize_binding) return { ok: false, error: response({ success: false, error_code: "WPS_DOCUMENT_UNBOUND", message: "当前文档尚未绑定，必须显式确认后才能写入", ...bindingDiagnostics(args, null) }) };
    meta = writeBinding(args);
  }
  const diagnostic = bindingDiagnostics(args, meta);
  if (diagnostic.binding_status !== "BOUND") {
    const legacy = diagnostic.binding_status === "LEGACY_BINDING_ID_MISMATCH";
    return { ok: false, error: response({ success: false, error_code: legacy ? "WPS_LEGACY_BINDING_ID_MISMATCH" : "WPS_DOCUMENT_BINDING_MISMATCH", message: legacy ? "当前文档使用旧版绑定标识，必须先显式升级" : "远端文档绑定与当前请求不一致", ...diagnostic }) };
  }
  return { ok: true, meta };
}

function updateBindingIdOnly(newBindingId) {
  const sheet = findSheet(META_SHEET);
  if (!sheet) throw new Error("binding metadata sheet not found");
  const values = sheet.Range("A1:B30").Value2 || [];
  for (let index = 0; index < values.length; index += 1) {
    const row = values[index];
    if (!row || String(row[0] || "") !== "binding_id") continue;
    sheet.Range(`B${index + 1}`).Value2 = String(newBindingId || "");
    return;
  }
  throw new Error("binding_id metadata row not found");
}

function migrateLegacyBinding(args) {
  const meta = readBinding();
  const diagnostic = bindingDiagnostics(args, meta);
  const expectedOldBindingId = String(args.expected_old_binding_id || "");
  const newBindingId = String(args.new_binding_id || "");
  const businessIdentityMatches = diagnostic.document_identity_match
    && diagnostic.site_identity_match
    && diagnostic.business_identity_match
    && diagnostic.target_code_match
    && diagnostic.target_type_match;
  if (!expectedOldBindingId || !newBindingId) {
    return response({ success: false, error_code: "WPS_BINDING_MIGRATION_ARGUMENT_INVALID", message: "旧版绑定迁移参数不完整", failed_operation: "VALIDATE_MIGRATION_ARGUMENTS", ...diagnostic });
  }
  if (!businessIdentityMatches) {
    return response({ success: false, error_code: "WPS_DOCUMENT_BINDING_MISMATCH", message: "远端业务身份不一致，禁止迁移旧版绑定标识", failed_operation: "VALIDATE_BUSINESS_IDENTITY", ...diagnostic });
  }
  if (diagnostic.remote_binding_id === newBindingId) {
    return response({ success: true, message: "远端文档已经使用当前稳定绑定标识", migrated: false, already_migrated: true, previous_binding_id: diagnostic.remote_binding_id, binding_id: newBindingId, ...diagnostic });
  }
  if (diagnostic.remote_binding_id !== expectedOldBindingId || !isLegacyBindingId(diagnostic.remote_binding_id)) {
    return response({ success: false, error_code: "WPS_DOCUMENT_BINDING_MISMATCH", message: "远端 Binding ID 已变化或不是可迁移的旧版标识", failed_operation: "VALIDATE_EXPECTED_OLD_BINDING_ID", expected_old_binding_id: expectedOldBindingId, ...diagnostic });
  }
  try {
    const previousBindingId = diagnostic.remote_binding_id;
    updateBindingIdOnly(newBindingId);
    const updated = readBinding();
    if (!updated || String(updated.binding_id || "") !== newBindingId) throw new Error("binding_id write verification failed");
    return response({ success: true, message: "旧版绑定标识已迁移", migrated: true, already_migrated: false, previous_binding_id: previousBindingId, binding_id: newBindingId, ...bindingDiagnostics(args, updated) });
  } catch (error) {
    return response({ success: false, error_code: "WPS_BINDING_MIGRATION_FAILED", message: String(error && error.message || error).slice(0, 500), failed_operation: "UPDATE_META_BINDING_ID", ...diagnostic });
  }
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

function toWpsColor(value) {
  const match = String(value || "").trim().match(/^#?([0-9a-f]{6})$/i);
  if (!match) throw new Error(`invalid RGB color: ${String(value || "")}`);
  const red = Number.parseInt(match[1].slice(0, 2), 16);
  const green = Number.parseInt(match[1].slice(2, 4), 16);
  const blue = Number.parseInt(match[1].slice(4, 6), 16);
  if (typeof RGB === "function") return RGB(red, green, blue);
  if (typeof Application !== "undefined" && typeof Application.RGB === "function") {
    return Application.RGB(red, green, blue);
  }
  return red + green * 256 + blue * 65536;
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
  if (definition.color) border.Color = toWpsColor(definition.color);
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
  if (font.color) attemptFormat(warnings, sheet.Name, "font_color", () => { range.Font.Color = toWpsColor(font.color); });
  if (font.underline) {
    const underline = font.underline === "double"
      ? enumValue("XlUnderlineStyle", "xlUnderlineStyleDouble", -4119)
      : enumValue("XlUnderlineStyle", "xlUnderlineStyleSingle", 2);
    attemptFormat(warnings, sheet.Name, "font_underline", () => { range.Font.Underline = underline; });
  }
  const fill = run.fill || {};
  if (fill.fg_color) attemptFormat(warnings, sheet.Name, "fill", () => { range.Interior.Color = toWpsColor(fill.fg_color); });
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
  if (sheetDto.tab_color) attemptFormat(warnings, sheet.Name, "tab_color", () => { sheet.Tab.Color = toWpsColor(sheetDto.tab_color); });
  attemptFormat(warnings, sheet.Name, "sheet_visibility", () => { sheet.Visible = sheetDto.sheet_visible !== false; });
  return verifyKeyFormatting(sheet, sheetDto, warnings);
}

function shanghaiDateTime(value) {
  const parsed = value ? new Date(value) : new Date();
  const timestamp = Number.isNaN(parsed.getTime()) ? Date.now() : parsed.getTime();
  const shifted = new Date(timestamp + 8 * 60 * 60 * 1000);
  const pad = (part) => String(part).padStart(2, "0");
  const date = `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`;
  const time = `${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}:${pad(shifted.getUTCSeconds())}`;
  return { date, dateTime: `${date} ${time}` };
}

function materializeRuntimeSheet(sheetDto, args, targetSyncTime) {
  const syncMode = sheetDto.sync_mode === "PREPEND_SNAPSHOT"
    ? "APPEND_SNAPSHOT"
    : sheetDto.sync_mode;
  if (sheetDto.logical_sheet_key !== "ap_online_history_overview") {
    return syncMode === sheetDto.sync_mode ? sheetDto : { ...sheetDto, sync_mode: syncMode };
  }
  const cells = (sheetDto.cells || []).map((row) => Array.isArray(row) ? [...row] : []);
  while (cells.length < 2) cells.push([]);
  const width = Math.max(Number(sheetDto.column_count) || 0, cells[0].length, cells[1].length, 1);
  while (cells[0].length < width) cells[0].push(null);
  while (cells[1].length < width) cells[1].push(null);
  cells[0][0] = `日期：${shanghaiDateTime(args.snapshot_generated_at).date}`;
  cells[1][0] = `更新时间：${targetSyncTime}`;
  return { ...sheetDto, sync_mode: syncMode, cells };
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

function writeStableSheet(sheetDto) {
  const sheet = ensureSheet(sheetDto.sheet_name);
  const values = sheetDto.cells || [];
  if (sheetDto.sync_mode === "APPEND_SNAPSHOT") {
    if (values.length) sheet.Range(`A1:A${values.length}`).EntireRow.Insert();
    if (values.length) sheet.Range("A1").Resize(values.length, sheetDto.column_count).Value2 = values;
  } else if (sheetDto.sync_mode === "FULL_REPLACE") {
    const used = sheet.UsedRange;
    if (used && used.ClearContents) used.ClearContents();
    if (values.length) sheet.Range("A1").Resize(values.length, sheetDto.column_count).Value2 = values;
  }
  return { written_rows: values.length, format_verification: { checked: false } };
}

function isSystemSheetName(name) {
  return String(name || "").startsWith("_NetConsole");
}

function orderedBusinessSheetNames(sheetDtos) {
  return (sheetDtos || [])
    .map((sheet, index) => ({ sheet, index }))
    .sort((left, right) => {
      const orderDifference = Number(left.sheet.sheet_order) - Number(right.sheet.sheet_order);
      return orderDifference || left.index - right.index;
    })
    .map(({ sheet }) => String(sheet.sheet_name || ""));
}

function sameSheetOrder(expected, actual) {
  return expected.length === actual.length && expected.every((name, index) => name === actual[index]);
}

function actualBusinessSheetOrder(expected) {
  const managedNames = new Set(expected);
  return sheetNames().filter((name) => managedNames.has(name));
}

function verifyBusinessSheetOrder(expected) {
  const actual = actualBusinessSheetOrder(expected);
  return { verified: sameSheetOrder(expected, actual), expected, actual };
}

function reorderBusinessSheets(sheetDtos) {
  const expected = orderedBusinessSheetNames(sheetDtos);
  for (let index = expected.length - 1; index >= 0; index -= 1) {
    const sheet = findSheet(expected[index]);
    if (!sheet) continue;
    const first = worksheets().Item(1);
    if (String(first.Name || "") !== String(sheet.Name || "")) sheet.Move(first);
  }
  return verifyBusinessSheetOrder(expected);
}

function writeAndVerifySheetTabColor(sheet, color) {
  if (!sheet || !sheet.Tab) throw new Error("Sheet.Tab API unavailable");
  const expected = toWpsColor(color);
  sheet.Tab.Color = expected;
  const actual = sheet.Tab.Color;
  return {
    verified: Number(actual) === Number(expected),
    expected,
    actual,
  };
}

function applyBusinessSheetTabColors(sheetDtos, warnings) {
  let applied = 0;
  for (const sheetDto of sheetDtos || []) {
    if (!sheetDto.tab_color) continue;
    const sheet = findSheet(sheetDto.sheet_name);
    if (!sheet) continue;
    const success = attemptFormat(warnings, sheet.Name, "sheet_tab_color", () => {
      const verification = writeAndVerifySheetTabColor(sheet, sheetDto.tab_color);
      if (!verification.verified) throw new Error("Sheet.Tab.Color readback mismatch");
    });
    if (success) applied += 1;
  }
  return applied;
}

function manageSystemSheets(expectedBusinessOrder, warnings) {
  const systemNames = sheetNames().filter(isSystemSheetName);
  for (const name of systemNames) {
    const sheet = findSheet(name);
    if (!sheet) continue;
    attemptFormat(warnings, name, "system_sheet_visibility", () => {
      sheet.Visible = false;
      if (!sheetIsHidden(sheet.Visible)) throw new Error("system sheet hidden state could not be verified");
    });
    const last = worksheets().Item(worksheets().Count);
    if (String(last.Name || "") !== name) {
      attemptFormat(warnings, name, "system_sheet_order", () => { sheet.Move(null, last); });
    }
  }
  const names = sheetNames();
  const lastBusinessIndex = expectedBusinessOrder.reduce(
    (value, name) => Math.max(value, names.indexOf(name)),
    -1,
  );
  const systemSheetOrderVerified = names.every(
    (name, index) => !isSystemSheetName(name) || index > lastBusinessIndex,
  );
  if (!systemSheetOrderVerified) {
    addFormatWarning(warnings, "_NetConsole*", "system_sheet_order", new Error("system sheets are not behind all business sheets"));
  }
  return { system_sheet_order_verified: systemSheetOrderVerified, actual_sheet_order_all: names };
}

function sync(payload) {
  const args = payload;
  if (args.protocol_version !== PROTOCOL_VERSION || args.target_type !== TARGET_TYPE) return response({ success: false, error_code: "WPS_PROTOCOL_MISMATCH", message: "protocol or target type mismatch" });
  const binding = assertBinding(args);
  if (!binding.ok) return binding.error;
  const sheets = args.workbook && args.workbook.sheets ? args.workbook.sheets : [];
  const targetSyncTime = shanghaiDateTime(new Date()).dateTime;
  const repeatedPrependBatch = Boolean(args.target_batch_id)
    && String(binding.meta.last_prepend_target_batch_id || "") === String(args.target_batch_id);
  let writtenRows = 0;
  let writtenSheets = 0;
  const formatWarnings = [];
  const sheetResults = [];
  const formatMirrorEnabled = FORMAT_MIRROR_EXPERIMENTAL && args.format_mirror_experimental === true;
  try {
    for (const sheet of sheets) {
      const runtimeSheet = materializeRuntimeSheet(sheet, args, targetSyncTime);
      const skipRepeatedPrepend = repeatedPrependBatch
        && sheet.sync_mode === "PREPEND_SNAPSHOT";
      const result = skipRepeatedPrepend
        ? { written_rows: 0, format_verification: { checked: false }, deduplicated: true }
        : formatMirrorEnabled
          ? writeSheet(runtimeSheet, formatWarnings)
          : writeStableSheet(runtimeSheet);
      if (!skipRepeatedPrepend && sheet.sync_mode === "PREPEND_SNAPSHOT") {
        binding.meta = updateBindingMetadata({
          last_prepend_target_batch_id: String(args.target_batch_id || ""),
        });
      }
      writtenRows += result.written_rows;
      writtenSheets += 1;
      sheetResults.push({ sheet_name: sheet.sheet_name, sync_mode: sheet.sync_mode, success: true, written_rows: result.written_rows, deduplicated: !!result.deduplicated, format_verification: result.format_verification });
    }
  } catch (error) {
    return response({ success: false, error_code: "WPS_SHEET_WRITE_FAILED", failed_sheet: sheets[writtenSheets] && sheets[writtenSheets].sheet_name || "", failed_operation: "WRITE_VALUES", written_sheet_count: writtenSheets, written_row_count: writtenRows, message: String(error && error.message || error).slice(0, 500), runtime_error_name: String(error && error.name || "Error"), runtime_error_stack: String(error && error.stack || "").slice(0, 2048), binding_status: "BOUND" });
  }
  const expectedSheetOrder = orderedBusinessSheetNames(sheets);
  let sheetOrderVerification;
  try {
    sheetOrderVerification = reorderBusinessSheets(sheets);
  } catch (error) {
    return response({ success: false, error_code: "WPS_SHEET_ORDER_VERIFY_FAILED", failed_operation: "REORDER_BUSINESS_SHEETS", written_sheet_count: writtenSheets, written_row_count: writtenRows, expected_sheet_order: expectedSheetOrder, actual_sheet_order: actualBusinessSheetOrder(expectedSheetOrder), message: String(error && error.message || error).slice(0, 500), runtime_error_name: String(error && error.name || "Error"), runtime_error_stack: String(error && error.stack || "").slice(0, 2048), binding_status: "BOUND" });
  }
  let systemSheetResult = { system_sheet_order_verified: false, actual_sheet_order_all: sheetNames() };
  try {
    systemSheetResult = manageSystemSheets(expectedSheetOrder, formatWarnings);
  } catch (error) {
    addFormatWarning(formatWarnings, "_NetConsole*", "system_sheet_order", error);
  }
  sheetOrderVerification = verifyBusinessSheetOrder(expectedSheetOrder);
  if (!sheetOrderVerification.verified) {
    return response({ success: false, error_code: "WPS_SHEET_ORDER_VERIFY_FAILED", failed_operation: "VERIFY_BUSINESS_SHEET_ORDER", written_sheet_count: writtenSheets, written_row_count: writtenRows, sheet_order_verified: false, expected_sheet_order: sheetOrderVerification.expected, actual_sheet_order: sheetOrderVerification.actual, message: "WPS 业务 Sheet 顺序与本地导出工作簿不一致", binding_status: "BOUND" });
  }
  const appliedTabColorCount = args.sheet_tab_color_enabled === true
    ? applyBusinessSheetTabColors(sheets, formatWarnings)
    : 0;
  try {
    binding.meta = updateBindingMetadata({
      last_sync_at: new Date().toISOString(),
      last_sync_revision: String(args.snapshot_revision || ""),
      last_target_batch_id: String(args.target_batch_id || ""),
    });
  } catch (error) {
    addFormatWarning(formatWarnings, META_SHEET, "sync_metadata", error);
  }
  const publicWarnings = formatWarnings.map(({ key, ...warning }) => warning);
  return response({ success: true, status: publicWarnings.length ? "SUCCESS_WITH_WARNINGS" : "SUCCESS", ...bindingDiagnostics(args, binding.meta), parent_batch_id: args.parent_batch_id, target_batch_id: args.target_batch_id, site_id: args.site_id, site_name: args.site_name, business_key: args.business_key, snapshot_revision: args.snapshot_revision, snapshot_sha256: args.snapshot_sha256, target_sync_executed_at: targetSyncTime, idempotent_prepend_replay: repeatedPrependBatch, written_sheet_count: writtenSheets, written_row_count: writtenRows, written_object_count: sheets.length, sheet_order_verified: true, expected_sheet_order: sheetOrderVerification.expected, actual_sheet_order: sheetOrderVerification.actual, ...systemSheetResult, sheet_tab_color_enabled: args.sheet_tab_color_enabled === true, applied_tab_color_count: appliedTabColorCount, format_mirror_experimental: formatMirrorEnabled, format_warning_count: publicWarnings.length, format_warnings: publicWarnings, sheets: sheetResults });
}

function sheetIsHidden(value) {
  const text = String(value).toLowerCase();
  return value === false || value === 0 || text === "0" || text === "false" || text === "xlsheethidden";
}

function probeScalarValue(value) {
  let current = value;
  while (Array.isArray(current)) current = current.length ? current[0] : "";
  return current;
}

function probeValueIsBlank(value) {
  if (Array.isArray(value)) return value.every((item) => probeValueIsBlank(item));
  return value === null || value === undefined || value === "";
}

function probeCapability(capabilities, failures, name, action) {
  try {
    capabilities[name] = action() === true;
    if (!capabilities[name]) failures.push({ capability: name, message: "能力验证结果为未通过" });
  } catch (error) {
    capabilities[name] = false;
    failures.push({ capability: name, message: String(error && error.message || error).slice(0, 300) });
  }
}

function runtimeWriteProbe(args) {
  const capabilities = {
    worksheet_enum: false,
    worksheet_item: false,
    worksheet_create: false,
    scalar_value2: false,
    matrix_value2: false,
    used_range: false,
    clear_contents: false,
    entire_row_insert: false,
    sheet_visibility: false,
  };
  const capabilityFailures = [];
  let sheets = null;
  let sheet = null;

  probeCapability(capabilities, capabilityFailures, "worksheet_enum", () => {
    sheets = worksheets();
    return Number(sheets.Count) >= 0;
  });
  probeCapability(capabilities, capabilityFailures, "worksheet_create", () => {
    sheet = ensureSheet(PROBE_SHEET);
    return Boolean(sheet);
  });
  probeCapability(capabilities, capabilityFailures, "worksheet_item", () => {
    if (!sheets || !sheet) return false;
    for (let index = 0; index < sheets.Count; index += 1) {
      if (String(sheets.Item(index + 1).Name || "") === PROBE_SHEET) return true;
    }
    return false;
  });
  probeCapability(capabilities, capabilityFailures, "scalar_value2", () => {
    if (!sheet) return false;
    const scalarRange = sheet.Range("A1");
    scalarRange.Value2 = "NetConsole runtime probe";
    return String(probeScalarValue(scalarRange.Value2) || "") === "NetConsole runtime probe";
  });
  probeCapability(capabilities, capabilityFailures, "matrix_value2", () => {
    if (!sheet) return false;
    const values = [["probe_id", String(args.probe_id || "")], [new Date().toISOString(), "2x2"]];
    sheet.Range("A2").Resize(2, 2).Value2 = values;
    return JSON.stringify(sheet.Range("A2").Resize(2, 2).Value2) === JSON.stringify(values);
  });
  probeCapability(capabilities, capabilityFailures, "used_range", () => Boolean(sheet && sheet.UsedRange));
  probeCapability(capabilities, capabilityFailures, "clear_contents", () => {
    if (!sheet) return false;
    const clearRange = sheet.Range("D1");
    clearRange.Value2 = "clear-me";
    clearRange.ClearContents();
    return probeValueIsBlank(clearRange.Value2);
  });
  probeCapability(capabilities, capabilityFailures, "entire_row_insert", () => {
    if (!sheet) return false;
    sheet.Range("A1").Value2 = "OLD";
    sheet.Range("A1").Resize(1, 1).EntireRow.Insert();
    sheet.Range("A1").Value2 = "NEW";
    return String(probeScalarValue(sheet.Range("A1").Value2) || "") === "NEW" && String(probeScalarValue(sheet.Range("A2").Value2) || "") === "OLD";
  });

  const coreCapabilities = {
    worksheet_enum: capabilities.worksheet_enum,
    worksheet_item: capabilities.worksheet_item,
    worksheet_create: capabilities.worksheet_create,
    scalar_value2: capabilities.scalar_value2,
    matrix_value2: capabilities.matrix_value2,
    used_range: capabilities.used_range,
    clear_contents: capabilities.clear_contents,
    entire_row_insert: capabilities.entire_row_insert,
  };
  const optionalFailures = [];
  probeCapability(capabilities, optionalFailures, "sheet_visibility", () => {
    if (!sheet || !("Visible" in sheet)) return false;
    sheet.Visible = false;
    return sheetIsHidden(sheet.Visible);
  });
  const optionalCapabilities = { sheet_visibility: capabilities.sheet_visibility };
  const fullReplaceReady = ["worksheet_enum", "worksheet_item", "worksheet_create", "scalar_value2", "matrix_value2", "used_range", "clear_contents"].every((name) => capabilities[name]);
  const prependSnapshotReady = fullReplaceReady && capabilities.entire_row_insert;
  const coreVerified = Object.values(coreCapabilities).every(Boolean);
  const warnings = optionalFailures.map((failure) => ({ capability: failure.capability, message: failure.capability === "sheet_visibility" ? "WPS 当前运行时无法确认系统 Sheet 隐藏状态" : failure.message }));

  try {
    if (sheet && sheet.UsedRange && sheet.UsedRange.ClearContents) sheet.UsedRange.ClearContents();
  } catch (error) {
    warnings.push({ capability: "probe_cleanup", message: String(error && error.message || error).slice(0, 300) });
  }
  const status = coreVerified ? (warnings.length ? "SUCCESS_WITH_WARNINGS" : "SUCCESS") : "FAILED";
  const failedNames = capabilityFailures.filter((failure) => !coreCapabilities[failure.capability]).map((failure) => failure.capability);
  return response({
    success: coreVerified,
    status: status,
    error_code: coreVerified ? "" : "WPS_RUNTIME_PROBE_VERIFY_FAILED",
    message: coreVerified ? (warnings.length ? "运行时核心能力探针通过，存在可选能力告警" : "运行时核心能力探针通过") : `运行时核心能力探针未通过：${failedNames.join(", ")}`,
    binding_status: readBinding() ? "BOUND" : "UNBOUND",
    runtime_capability: coreVerified ? "VERIFIED" : "DEPLOYMENT_PENDING",
    core_verified: coreVerified,
    full_replace_ready: fullReplaceReady,
    prepend_snapshot_ready: prependSnapshotReady,
    capabilities: capabilities,
    core_capabilities: coreCapabilities,
    optional_capabilities: optionalCapabilities,
    capability_failures: capabilityFailures,
    warnings: warnings,
    probe_sheet: PROBE_SHEET,
    probe_id: args.probe_id,
  });
}

function sheetOrderProbe(args) {
  const firstName = PROBE_SHEET;
  const secondName = "_NetConsoleSyncTest";
  const expectedSheetOrder = [firstName, secondName];
  const warnings = [];
  try {
    const first = ensureSheet(firstName);
    const second = ensureSheet(secondName);
    second.Move(first);
    const beforeOrder = sheetNames().filter((name) => expectedSheetOrder.includes(name));
    const beforeVerified = sameSheetOrder([secondName, firstName], beforeOrder);
    second.Move(null, first);
    const afterOrder = sheetNames().filter((name) => expectedSheetOrder.includes(name));
    const afterVerified = sameSheetOrder(expectedSheetOrder, afterOrder);
    const systemSheetResult = manageSystemSheets([], warnings);
    const actualSheetOrder = sheetNames().filter((name) => expectedSheetOrder.includes(name));
    const verified = beforeVerified && afterVerified && sameSheetOrder(expectedSheetOrder, actualSheetOrder);
    const publicWarnings = warnings.map(({ key, ...warning }) => warning);
    return response({
      success: verified,
      status: verified ? (publicWarnings.length ? "SUCCESS_WITH_WARNINGS" : "SUCCESS") : "FAILED",
      error_code: verified ? "" : "WPS_SHEET_ORDER_VERIFY_FAILED",
      message: verified ? "Sheet.Move 排序探针通过" : "Sheet.Move 排序后读回顺序不一致",
      ...bindingDiagnostics(args),
      sheet_order_verified: verified,
      sheet_move_before_verified: beforeVerified,
      sheet_move_after_verified: afterVerified,
      expected_sheet_order: expectedSheetOrder,
      actual_sheet_order: actualSheetOrder,
      before_probe_order: beforeOrder,
      after_probe_order: afterOrder,
      ...systemSheetResult,
      format_warning_count: publicWarnings.length,
      format_warnings: publicWarnings,
      warnings: publicWarnings,
      probe_id: args.probe_id,
    });
  } catch (error) {
    return response({ success: false, status: "FAILED", error_code: "WPS_SHEET_ORDER_VERIFY_FAILED", failed_operation: "SHEET_MOVE_PROBE", message: String(error && error.message || error).slice(0, 500), runtime_error_name: String(error && error.name || "Error"), runtime_error_stack: String(error && error.stack || "").slice(0, 2048), ...bindingDiagnostics(args), sheet_order_verified: false, expected_sheet_order: expectedSheetOrder, actual_sheet_order: sheetNames().filter((name) => expectedSheetOrder.includes(name)), probe_id: args.probe_id });
  }
}

function sheetTabColorProbe(args) {
  const sheetName = "_NetConsoleSyncTest";
  const color = "#C6EFCE";
  try {
    const sheet = ensureSheet(sheetName);
    const verification = writeAndVerifySheetTabColor(sheet, color);
    if ("Visible" in sheet) sheet.Visible = false;
    return response({
      success: verification.verified,
      status: verification.verified ? "SUCCESS" : "FAILED",
      error_code: verification.verified ? "" : "WPS_SHEET_TAB_COLOR_VERIFY_FAILED",
      message: verification.verified ? "Sheet 标签颜色探针通过" : "Sheet 标签颜色写后读回不一致",
      ...bindingDiagnostics(args),
      sheet_tab_color_verified: verification.verified,
      expected_tab_color: color,
      expected_tab_color_value: verification.expected,
      actual_tab_color: verification.actual,
      probe_sheet: sheetName,
      probe_id: args.probe_id,
    });
  } catch (error) {
    return response({ success: false, status: "FAILED", error_code: "WPS_SHEET_TAB_COLOR_VERIFY_FAILED", failed_operation: "SHEET_TAB_COLOR_PROBE", message: String(error && error.message || error).slice(0, 500), runtime_error_name: String(error && error.name || "Error"), runtime_error_stack: String(error && error.stack || "").slice(0, 2048), ...bindingDiagnostics(args), sheet_tab_color_verified: false, expected_tab_color: color, actual_tab_color: "", probe_sheet: sheetName, probe_id: args.probe_id });
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
  if (args.operation === "connection_test") return connectionTest(args);
  if (args.operation === "migrate_legacy_binding") return migrateLegacyBinding(args);
  if (args.operation === "runtime_write_probe") return runtimeWriteProbe(args);
  if (args.operation === "sheet_order_probe") return sheetOrderProbe(args);
  if (args.operation === "sheet_tab_color_probe") return sheetTabColorProbe(args);
  if (args.operation === "sync_test_sheet") return syncTestSheet(args);
  if (args.operation === "sync_trackside_ap_business") return sync(args);
  return response({ success: false, error_code: "OPERATION_UNSUPPORTED", message: "unsupported operation" });
}

// Explicit execution entry point. Confirm the returned JSON in the WPS editor
// before using the newly copied webhook in production.
return main();
