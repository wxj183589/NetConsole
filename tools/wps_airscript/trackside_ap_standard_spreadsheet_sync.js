// NetConsole WPS_STANDARD_SPREADSHEET AirScript protocol v2.
// Publish this script in the ordinary online spreadsheet document.
// The exact workbook API names are kept in these small helpers so a WPS
// runtime upgrade does not change the NetConsole payload contract.
const PROTOCOL_VERSION = 2;
const SCRIPT_VERSION = "2.8.4-standard";
const DEPLOYMENT_ID = "trackside-ap-standard-2.8.4";
const DOCUMENT_ID = "549847228994";
const TARGET_TYPE = "WPS_STANDARD_SPREADSHEET";
const TARGET_CODE = "wps_standard_spreadsheet";
const RUNTIME_CAPABILITY = "VERIFIED";
const META_SHEET = "_NetConsoleSyncMeta";
const PROBE_SHEET = "_NetConsoleRuntimeProbe";
const FORMAT_MIRROR_ENABLED = true;
const COLUMN_WIDTH_TOLERANCE = 0.5;
const ROW_HEIGHT_TOLERANCE = 0.5;
const MAX_FORMAT_RUNS_PER_SHEET = 1000;
const FREEZE_MODE_NONE = "NONE";
const FREEZE_MODE_FIRST_ROW_ONLY = "FIRST_ROW_ONLY";

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

function readManagedRanges(meta) {
  try {
    const parsed = JSON.parse(String(meta && meta.managed_ranges_json || "{}"));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (_error) {
    return {};
  }
}

function managedRangeSize(sheetDto) {
  const values = Array.isArray(sheetDto.cells) ? sheetDto.cells : [];
  const rowCount = Math.max(Number(sheetDto.row_count) || 0, values.length, 1);
  const valueColumns = values.reduce(
    (maximum, row) => Math.max(maximum, Array.isArray(row) ? row.length : 0),
    0,
  );
  const columnCount = Math.max(Number(sheetDto.column_count) || 0, valueColumns, 1);
  return { row_count: rowCount, column_count: columnCount };
}

function clearFullReplaceTarget(sheet, sheetDto, previousManaged) {
  const current = managedRangeSize(sheetDto);
  const previousRows = Math.max(Number(previousManaged && previousManaged.row_count) || 0, 0);
  const previousColumns = Math.max(Number(previousManaged && previousManaged.column_count) || 0, 0);
  if (!previousRows && !previousColumns) {
    const used = sheet.UsedRange;
    if (used) {
      if (used.UnMerge) used.UnMerge();
      if (used.ClearContents) used.ClearContents();
      if (used.ClearFormats) used.ClearFormats();
    }
  }
  const clearRows = Math.max(previousRows, current.row_count, 1);
  const clearColumns = Math.max(previousColumns, current.column_count, 1);
  const target = sheet.Range("A1").Resize(clearRows, clearColumns);
  if (target.UnMerge) target.UnMerge();
  if (!target.ClearContents) throw new Error("Range.ClearContents API unavailable");
  if (!target.ClearFormats) throw new Error("Range.ClearFormats API unavailable");
  target.ClearContents();
  target.ClearFormats();
  return current;
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

function addFormatWarning(warnings, sheetName, feature, error, range = "") {
  const reason = String(error && error.message || error || "unsupported").slice(0, 300);
  const key = `${sheetName}|${feature}|${range}|${reason}`;
  if (warnings.some((item) => item.key === key) || warnings.length >= 100) return;
  warnings.push({ key, sheet_name: sheetName, feature, range, reason });
}

function attemptFormat(warnings, sheetName, feature, action, range = "") {
  try {
    action();
    return true;
  } catch (error) {
    addFormatWarning(warnings, sheetName, feature, error, range);
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

function wpsColorToHex(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  const normalized = Math.trunc(number) >>> 0;
  const red = normalized & 0xff;
  const green = (normalized >>> 8) & 0xff;
  const blue = (normalized >>> 16) & 0xff;
  const hex = (part) => part.toString(16).padStart(2, "0").toUpperCase();
  return `#${hex(red)}${hex(green)}${hex(blue)}`;
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

function borderDefinitionFromSheet(sheetDto) {
  for (const run of sheetDto && sheetDto.format_runs || []) {
    const borders = run && run.border || {};
    for (const sideName of ["left", "right", "top", "bottom"]) {
      const definition = borders[sideName];
      if (definition && definition.style) return definition;
    }
  }
  return null;
}

function columnLetters(number) {
  let value = Math.max(1, Number(number) || 1);
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function nonEmptyRowRanges(sheetDto) {
  const rowCount = Math.max(Number(sheetDto && sheetDto.row_count) || 0, 1);
  const columnCount = Math.max(Number(sheetDto && sheetDto.column_count) || 0, 1);
  const cells = Array.isArray(sheetDto && sheetDto.cells) ? sheetDto.cells : [];
  const lastColumn = columnLetters(columnCount);
  const ranges = [];
  let startRow = 0;
  for (let row = 1; row <= rowCount + 1; row += 1) {
    const values = row <= rowCount && Array.isArray(cells[row - 1]) ? cells[row - 1] : [];
    const hasValue = row <= rowCount && values.some((value) => value !== null && value !== undefined && String(value) !== "");
    if (hasValue && startRow === 0) startRow = row;
    if ((!hasValue || row === rowCount + 1) && startRow > 0) {
      const endRow = row - 1;
      ranges.push(`A${startRow}:${lastColumn}${endRow}`);
      startRow = 0;
    }
  }
  return ranges.length ? ranges : [`A1:${lastColumn}${rowCount}`];
}

function setAllBorders(range, definition, options = {}) {
  const entries = {
    left: ["xlEdgeLeft", 7],
    top: ["xlEdgeTop", 8],
    bottom: ["xlEdgeBottom", 9],
    right: ["xlEdgeRight", 10],
  };
  if (options.includeInsideHorizontal) entries.inside_horizontal = ["xlInsideHorizontal", 12];
  if (options.includeInsideVertical) entries.inside_vertical = ["xlInsideVertical", 11];
  for (const [sideName, entry] of Object.entries(entries)) {
    const border = range.Borders.Item(enumValue("XlBordersIndex", entry[0], entry[1]));
    const style = borderDefinition(definition.style);
    border.LineStyle = style.lineStyle;
    border.Weight = style.weight;
    if (definition.color) border.Color = toWpsColor(definition.color);
  }
}

function readAllBorders(range, definition, options = {}) {
  const entries = {
    left: ["xlEdgeLeft", 7],
    top: ["xlEdgeTop", 8],
    bottom: ["xlEdgeBottom", 9],
    right: ["xlEdgeRight", 10],
  };
  if (options.includeInsideHorizontal) entries.inside_horizontal = ["xlInsideHorizontal", 12];
  if (options.includeInsideVertical) entries.inside_vertical = ["xlInsideVertical", 11];
  const style = borderDefinition(definition.style);
  const expected = {};
  const actual = {};
  let verified = true;
  for (const [sideName, entry] of Object.entries(entries)) {
    const border = range.Borders.Item(enumValue("XlBordersIndex", entry[0], entry[1]));
    const expectedSide = { line_style: style.lineStyle, weight: style.weight, color: definition.color || "" };
    const actualSide = { line_style: Number(border.LineStyle), weight: Number(border.Weight), color: definition.color ? wpsColorToHex(border.Color) : "" };
    expected[sideName] = expectedSide;
    actual[sideName] = actualSide;
    verified = verified
      && Number(actualSide.line_style) === Number(expectedSide.line_style)
      && Number(actualSide.weight) === Number(expectedSide.weight)
      && (!expectedSide.color || actualSide.color === String(expectedSide.color).toUpperCase());
  }
  return { verified, expected, actual, all_borders: true };
}

function applyAllBorders(sheet, sheetDto, warnings, report) {
  const definition = borderDefinitionFromSheet(sheetDto);
  if (!definition) return;
  for (const rangeAddress of nonEmptyRowRanges(sheetDto)) {
    const rowMatch = String(rangeAddress).match(/^[A-Z]+(\d+):[A-Z]+(\d+)$/);
    const options = {
      includeInsideHorizontal: !rowMatch || Number(rowMatch[1]) < Number(rowMatch[2]),
      includeInsideVertical: Number(sheetDto.column_count) > 1,
    };
    verifiedFormatOperation(report, warnings, sheet.Name, "border", rangeAddress, () => {
      setAllBorders(sheet.Range(rangeAddress), definition, options);
    }, () => readAllBorders(sheet.Range(rangeAddress), definition, options), { allBorders: true });
  }
}

function emptyFormatFeature() {
  return { status: "SUCCESS", attempted_count: 0, applied_count: 0, read_back_count: 0, verified_count: 0, warning_count: 0, failed_count: 0, examples: [], items: [] };
}

function createFormatResults() {
  return {
    row_height: emptyFormatFeature(),
    font: emptyFormatFeature(),
    fill: emptyFormatFeature(),
    number_format: emptyFormatFeature(),
    alignment: emptyFormatFeature(),
    merge: emptyFormatFeature(),
    border: emptyFormatFeature(),
    freeze_panes: emptyFormatFeature(),
    auto_filter: emptyFormatFeature(),
    sheet_tab_color: emptyFormatFeature(),
    sheet_order: emptyFormatFeature(),
    sample_data: emptyFormatFeature(),
  };
}

function compactValue(value) {
  if (value === undefined) return "undefined";
  if (typeof value === "string") return value.slice(0, 180);
  try { return JSON.stringify(value).slice(0, 180); } catch (_error) { return String(value).slice(0, 180); }
}

function keepFormatExample(feature, sheetName, range, expected, actual, verified) {
  if (feature.examples.length >= 20) return;
  if (!verified || feature.examples.length < 3) {
    feature.examples.push({ sheet_name: sheetName, range, expected: compactValue(expected), actual: compactValue(actual), verified });
  }
}

function verifiedFormatOperation(report, warnings, sheetName, featureName, range, apply, readBack, metadata = {}) {
  const feature = report[featureName];
  feature.attempted_count += 1;
  try {
    apply();
    feature.applied_count += 1;
  } catch (error) {
    feature.failed_count += 1;
    feature.warning_count += 1;
    keepFormatExample(feature, sheetName, range, "write", String(error && error.message || error), false);
    addFormatWarning(warnings, sheetName, featureName, error, range);
    return false;
  }
  try {
    const result = readBack();
    feature.read_back_count += 1;
    const verified = !!result.verified;
    if (["freeze_panes", "border", "sample_data"].includes(featureName)) {
      feature.items.push({ sheet_name: sheetName, range, verified, ...metadata, ...result });
    }
    if (verified) feature.verified_count += 1;
    else {
      feature.failed_count += 1;
      feature.warning_count += 1;
      const message = result.error_message
        || `readback mismatch: expected=${compactValue(result.expected)}, actual=${compactValue(result.actual)}`;
      addFormatWarning(warnings, sheetName, featureName, new Error(message), range);
    }
    keepFormatExample(feature, sheetName, range, result.expected, result.actual, verified);
    return verified;
  } catch (error) {
    feature.failed_count += 1;
    feature.warning_count += 1;
    keepFormatExample(feature, sheetName, range, "readback", String(error && error.message || error), false);
    addFormatWarning(warnings, sheetName, featureName, error, range);
    return false;
  }
}

function finalizeFormatResults(report) {
  for (const feature of Object.values(report)) {
    feature.status = feature.failed_count || feature.warning_count ? "SUCCESS_WITH_WARNINGS" : "SUCCESS";
  }
  return report;
}

function fontReadback(range, font) {
  const expected = {};
  const actual = {};
  let verified = true;
  if (font.name) { expected.name = String(font.name); actual.name = String(range.Font.Name || ""); verified = verified && actual.name === expected.name; }
  if (font.size) { expected.size = Number(font.size); actual.size = Number(range.Font.Size); verified = verified && Math.abs(actual.size - expected.size) <= 0.1; }
  for (const key of ["bold", "italic", "strike"]) {
    if (!(key in font)) continue;
    const property = key === "strike" ? "Strikethrough" : key.charAt(0).toUpperCase() + key.slice(1);
    expected[key] = !!font[key];
    actual[key] = !!range.Font[property];
    verified = verified && actual[key] === expected[key];
  }
  if (font.underline) {
    expected.underline = font.underline === "double"
      ? enumValue("XlUnderlineStyle", "xlUnderlineStyleDouble", -4119)
      : enumValue("XlUnderlineStyle", "xlUnderlineStyleSingle", 2);
    actual.underline = Number(range.Font.Underline);
    verified = verified && actual.underline === Number(expected.underline);
  }
  if (font.color) { expected.color = String(font.color).toUpperCase(); actual.color = wpsColorToHex(range.Font.Color); verified = verified && actual.color === expected.color; }
  return { verified, expected, actual };
}

function alignmentReadback(range, alignment) {
  const horizontal = horizontalAlignment(alignment.horizontal);
  const vertical = verticalAlignment(alignment.vertical);
  const expected = {
    horizontal,
    vertical,
    wrap_text: !!alignment.wrap_text,
    text_rotation: Number(alignment.text_rotation || 0),
    shrink_to_fit: !!alignment.shrink_to_fit,
  };
  const actual = {
    horizontal: range.HorizontalAlignment,
    vertical: range.VerticalAlignment,
    wrap_text: !!range.WrapText,
    text_rotation: Number(range.Orientation || 0),
    shrink_to_fit: !!range.ShrinkToFit,
  };
  let verified = (horizontal === null || Number(actual.horizontal) === Number(horizontal))
    && (vertical === null || Number(actual.vertical) === Number(vertical))
    && (!("wrap_text" in alignment) || actual.wrap_text === expected.wrap_text)
    && (!("text_rotation" in alignment) || actual.text_rotation === expected.text_rotation)
    && (!("shrink_to_fit" in alignment) || actual.shrink_to_fit === expected.shrink_to_fit);
  try {
    const display = range.DisplayFormat;
    actual.display_horizontal = display.HorizontalAlignment;
    if (horizontal !== null) verified = verified && Number(actual.display_horizontal) === Number(horizontal);
  } catch (_error) { /* DisplayFormat is optional readback evidence. */ }
  return { verified, expected, actual };
}

function sampleFormatReadback(range, expectedFormat, expectedDisplayText) {
  const expected = {};
  const actual = {};
  let verified = true;
  const font = expectedFormat.font || {};
  if (Object.keys(font).length) {
    const result = fontReadback(range, font);
    expected.font = result.expected;
    actual.font = result.actual;
    verified = verified && result.verified;
  }
  const fill = expectedFormat.fill || {};
  if (fill.fg_color) {
    expected.fill = String(fill.fg_color).toUpperCase();
    actual.fill = wpsColorToHex(range.Interior.Color);
    verified = verified && actual.fill === expected.fill;
  }
  if (expectedFormat.number_format) {
    expected.number_format = String(expectedFormat.number_format);
    actual.number_format = String(range.NumberFormat || "");
    verified = verified && actual.number_format === expected.number_format;
  }
  const alignment = expectedFormat.alignment || {};
  if (Object.keys(alignment).length) {
    const result = alignmentReadback(range, alignment);
    expected.alignment = result.expected;
    actual.alignment = result.actual;
    verified = verified && result.verified;
  }
  if (expectedDisplayText !== undefined && expectedDisplayText !== null) {
    expected.display_text = String(expectedDisplayText);
    actual.display_text = String(range.Text || "");
    verified = verified && actual.display_text === expected.display_text;
  }
  return { verified, expected, actual };
}

function applyFormatRun(sheet, run, warnings, report) {
  if (!run || !run.range) return;
  const range = sheet.Range(run.range);
  const font = run.font || {};
  if (Object.keys(font).length) {
    verifiedFormatOperation(report, warnings, sheet.Name, "font", run.range, () => {
      if (font.name) range.Font.Name = font.name;
      if (font.size) range.Font.Size = font.size;
      if ("bold" in font) range.Font.Bold = !!font.bold;
      if ("italic" in font) range.Font.Italic = !!font.italic;
      if ("strike" in font) range.Font.Strikethrough = !!font.strike;
      if (font.color) range.Font.Color = toWpsColor(font.color);
      if (font.underline) range.Font.Underline = font.underline === "double"
        ? enumValue("XlUnderlineStyle", "xlUnderlineStyleDouble", -4119)
        : enumValue("XlUnderlineStyle", "xlUnderlineStyleSingle", 2);
    }, () => fontReadback(range, font));
  }
  const fill = run.fill || {};
  if (fill.fg_color) {
    verifiedFormatOperation(report, warnings, sheet.Name, "fill", run.range, () => {
      range.Interior.Color = toWpsColor(fill.fg_color);
    }, () => {
      const actual = wpsColorToHex(range.Interior.Color);
      let displayColor = "";
      try { displayColor = wpsColorToHex(range.DisplayFormat.Interior.Color); } catch (_error) { displayColor = ""; }
      return { verified: actual === String(fill.fg_color).toUpperCase(), expected: fill.fg_color, actual: { color: actual, display_color: displayColor } };
    });
  }
  if (run.number_format) {
    verifiedFormatOperation(report, warnings, sheet.Name, "number_format", run.range, () => {
      range.NumberFormat = run.number_format;
    }, () => ({ verified: String(range.NumberFormat || "") === String(run.number_format), expected: run.number_format, actual: String(range.NumberFormat || "") }));
  }
  const alignment = run.alignment || {};
  if (Object.keys(alignment).length) {
    const horizontal = horizontalAlignment(alignment.horizontal);
    const vertical = verticalAlignment(alignment.vertical);
    verifiedFormatOperation(report, warnings, sheet.Name, "alignment", run.range, () => {
      if (horizontal !== null) range.HorizontalAlignment = horizontal;
      if (vertical !== null) range.VerticalAlignment = vertical;
      if ("wrap_text" in alignment) range.WrapText = !!alignment.wrap_text;
      if (alignment.text_rotation) range.Orientation = alignment.text_rotation;
      if ("shrink_to_fit" in alignment) range.ShrinkToFit = !!alignment.shrink_to_fit;
    }, () => alignmentReadback(range, alignment));
  }
  const borders = run.border || {};
  for (const sideName of ["left", "top", "bottom", "right"]) {
    const definition = borders[sideName];
    if (!definition) continue;
    verifiedFormatOperation(report, warnings, sheet.Name, "border", `${run.range}:${sideName}`, () => {
      applyBorder(range, sideName, definition);
    }, () => {
      const names = { left: ["xlEdgeLeft", 7], top: ["xlEdgeTop", 8], bottom: ["xlEdgeBottom", 9], right: ["xlEdgeRight", 10] };
      const border = range.Borders.Item(enumValue("XlBordersIndex", names[sideName][0], names[sideName][1]));
      const style = borderDefinition(definition.style);
      const expected = { line_style: style.lineStyle, weight: style.weight, color: definition.color || "" };
      const actual = { line_style: border.LineStyle, weight: border.Weight, color: definition.color ? wpsColorToHex(border.Color) : "" };
      return { verified: Number(actual.line_style) === Number(expected.line_style) && Number(actual.weight) === Number(expected.weight) && (!expected.color || actual.color === String(expected.color).toUpperCase()), expected, actual };
    });
  }
}

function formatTargetRange(sheet, sheetDto) {
  const rows = Math.max(Number(sheetDto.row_count) || 0, 1);
  const columns = Math.max(Number(sheetDto.column_count) || 0, 1);
  return sheet.Range("A1").Resize(rows, columns);
}

function prepareFormatTarget(sheet, sheetDto, warnings) {
  const range = formatTargetRange(sheet, sheetDto);
  attemptFormat(warnings, sheet.Name, "format_unmerge", () => { if (range.UnMerge) range.UnMerge(); });
  attemptFormat(warnings, sheet.Name, "format_clear", () => {
    if (!range.ClearFormats) throw new Error("Range.ClearFormats API unavailable");
    range.ClearFormats();
  });
  return range;
}

function applyRowHeights(sheet, sheetDto, targetRange, warnings, report) {
  const entries = Object.entries(sheetDto.row_heights || {})
    .map(([row, heightValue]) => ({ row: Number(row), height: Number(heightValue) }))
    .filter((item) => Number.isInteger(item.row) && item.row > 0 && Number.isFinite(item.height))
    .sort((left, right) => left.row - right.row);
  let index = 0;
  while (index < entries.length) {
    const start = entries[index];
    let endIndex = index;
    while (
      endIndex + 1 < entries.length
      && entries[endIndex + 1].row === entries[endIndex].row + 1
      && Math.abs(entries[endIndex + 1].height - start.height) <= ROW_HEIGHT_TOLERANCE
    ) endIndex += 1;
    const end = entries[endIndex];
    const rangeAddress = start.row === end.row ? `${start.row}:${start.row}` : `${start.row}:${end.row}`;
    const expected = start.height;
    attemptFormat(warnings, sheet.Name, "row_height_baseline", () => {
      sheet.Range(rangeAddress).RowHeight = expected;
    }, rangeAddress);
    index = endIndex + 1;
  }
  if (sheetDto.auto_fit_rows) {
    verifiedFormatOperation(report, warnings, sheet.Name, "row_height", targetRange.Address || `A1:${sheetDto.row_count}`, () => {
      if (!targetRange.Rows || !targetRange.Rows.AutoFit) throw new Error("Range.Rows.AutoFit API unavailable");
      targetRange.Rows.AutoFit();
    }, () => {
      const sampleRows = [...new Set([1, Math.max(1, Math.ceil(Number(sheetDto.row_count || 1) / 2)), Math.max(1, Number(sheetDto.row_count || 1))])];
      const actual = sampleRows.map((row) => dimensionValue(sheet.Range(`${row}:${row}`).RowHeight));
      return { verified: actual.every((height) => height !== null && height > 0), expected: "Rows.AutoFit", actual };
    });
  }
  if (!entries.length) return;
  verifiedFormatOperation(report, warnings, sheet.Name, "row_height", "minimum_row_heights", () => {
    for (const entry of entries) {
      const row = sheet.Range(`${entry.row}:${entry.row}`);
      const actual = Number(row.RowHeight);
      if (!Number.isFinite(actual) || actual < entry.height) row.RowHeight = entry.height;
    }
  }, () => {
    const failedRows = [];
    for (const entry of entries) {
      const actual = dimensionValue(sheet.Range(`${entry.row}:${entry.row}`).RowHeight);
      if (actual === null || actual + ROW_HEIGHT_TOLERANCE < entry.height) {
        failedRows.push({ row: entry.row, minimum: entry.height, actual });
        if (failedRows.length >= 10) break;
      }
    }
    return {
      verified: !failedRows.length,
      expected: { minimum_count: entries.length },
      actual: { failed_rows: failedRows },
    };
  });
}

function applyMerges(sheet, sheetDto, warnings, report) {
  for (const merge of sheetDto.merges || []) {
    verifiedFormatOperation(report, warnings, sheet.Name, "merge", merge, () => { sheet.Range(merge).Merge(); }, () => {
      const range = sheet.Range(merge);
      let actual = "";
      try {
        actual = normalizeAddress(range.MergeArea && range.MergeArea.Address);
      } catch (_error) {
        actual = normalizeAddress(range.Address);
      }
      const expected = normalizeAddress(merge);
      return { verified: !!range.MergeCells && actual === expected, expected, actual };
    });
  }
}

function optionalWindowNumber(window, propertyName) {
  try {
    if (!(propertyName in window)) return null;
    const value = Number(window[propertyName]);
    return Number.isFinite(value) ? value : null;
  } catch (_error) {
    return null;
  }
}

function activeSheetName() {
  try {
    return String(Application.ActiveSheet && Application.ActiveSheet.Name || "");
  } catch (_error) {
    return "";
  }
}

function activeCellState() {
  try {
    const cell = Application.ActiveCell;
    return {
      row: Number(cell && cell.Row) || 0,
      column: Number(cell && cell.Column) || 0,
    };
  } catch (_error) {
    return { row: 0, column: 0 };
  }
}

function freezeState(window) {
  return {
    freeze: !!window.FreezePanes,
    split_row: optionalWindowNumber(window, "SplitRow"),
    split_column: optionalWindowNumber(window, "SplitColumn"),
    split_horizontal: optionalWindowNumber(window, "SplitHorizontal"),
    split_vertical: optionalWindowNumber(window, "SplitVertical"),
    scroll_row: optionalWindowNumber(window, "ScrollRow"),
    scroll_column: optionalWindowNumber(window, "ScrollColumn"),
  };
}

function paneDiagnostics(window) {
  return {
    active_sheet: activeSheetName(),
    active_cell: activeCellState(),
    ...freezeState(window),
  };
}

function expectedFreezeState(sheetDto) {
  const mode = sheetDto.logical_sheet_key === "ap_online_history_overview"
    ? FREEZE_MODE_NONE
    : FREEZE_MODE_FIRST_ROW_ONLY;
  return {
    mode,
    freeze: mode === FREEZE_MODE_FIRST_ROW_ONLY,
    split_row: mode === FREEZE_MODE_FIRST_ROW_ONLY ? 1 : 0,
    split_column: 0,
  };
}

function freezeStateMatches(actual, expected) {
  if (actual.freeze !== expected.freeze
      || actual.split_row !== expected.split_row
      || actual.split_column !== expected.split_column) return false;
  if (actual.split_vertical !== null && actual.split_vertical !== 0) return false;
  if (!expected.freeze && actual.split_horizontal !== null && actual.split_horizontal !== 0) return false;
  return true;
}

function setOptionalWindowNumber(window, propertyName, expectedValue) {
  let supported = false;
  try {
    supported = propertyName in window;
  } catch (_error) {
    return { supported: false, actual: null };
  }
  if (!supported) return { supported: false, actual: null };
  try {
    window[propertyName] = expectedValue;
    const actual = Number(window[propertyName]);
    if (!Number.isFinite(actual) || actual !== expectedValue) {
      throw new Error(`expected ${expectedValue}, actual ${actual}`);
    }
    return { supported: true, actual };
  } catch (error) {
    throw new Error(`WPS_FREEZE_RESET_FAILED: ${propertyName}: ${String(error && error.message || error)}`);
  }
}

function resetWindowPaneState(sheet) {
  if (!sheet || typeof sheet.Activate !== "function") {
    throw new Error("WPS_FREEZE_RESET_FAILED: worksheet activate API unavailable");
  }
  sheet.Activate();
  if (activeSheetName() !== String(sheet.Name || "")) {
    throw new Error(`WPS_FREEZE_RESET_FAILED: expected active sheet ${sheet.Name}, actual ${activeSheetName() || "?"}`);
  }
  const window = Application.ActiveWindow;
  if (!window) throw new Error("WPS_FREEZE_RESET_FAILED: active window unavailable");
  const before = paneDiagnostics(window);
  window.FreezePanes = false;
  window.SplitRow = 0;
  window.SplitColumn = 0;
  const optional_reset = {
    split_horizontal: setOptionalWindowNumber(window, "SplitHorizontal", 0),
    split_vertical: setOptionalWindowNumber(window, "SplitVertical", 0),
    scroll_row: setOptionalWindowNumber(window, "ScrollRow", 1),
    scroll_column: setOptionalWindowNumber(window, "ScrollColumn", 1),
  };
  const after_reset = paneDiagnostics(window);
  if (after_reset.freeze || after_reset.split_row !== 0 || after_reset.split_column !== 0) {
    throw new Error(`WPS_FREEZE_RESET_FAILED: split_row=${after_reset.split_row}, split_column=${after_reset.split_column}, freeze=${after_reset.freeze}`);
  }
  return { window, before, after_reset, optional_reset };
}

function selectFirstRowFreezeAnchor(sheet) {
  const anchor = sheet.Range("A2");
  if (!anchor || typeof anchor.Select !== "function") {
    throw new Error("WPS_FREEZE_SELECTION_FAILED: A2 selection API unavailable");
  }
  try {
    anchor.Select();
  } catch (error) {
    throw new Error(`WPS_FREEZE_SELECTION_FAILED: ${String(error && error.message || error)}`);
  }
  const activeSheet = activeSheetName();
  const activeCell = activeCellState();
  if (activeSheet !== String(sheet.Name || "") || activeCell.row !== 2 || activeCell.column !== 1) {
    throw new Error(`WPS_FREEZE_SELECTION_FAILED: expected ${sheet.Name}!A2, actual ${activeSheet || "?"}!${activeCell.column || "?"}:${activeCell.row || "?"}`);
  }
  return paneDiagnostics(Application.ActiveWindow);
}

function applyFreezeMode(sheet, sheetDto, reactivationSheet, warnings, report) {
  const expected = expectedFreezeState(sheetDto);
  const requestedMode = String(sheetDto.freeze_mode || "").trim().toUpperCase();
  const diagnostics = {
    requested_mode: requestedMode,
    contract_mode: expected.mode,
    before: null,
    after_reset: null,
    after_select: null,
    immediate: null,
    reactivated: null,
    reactivation_switch_sheet: reactivationSheet ? String(reactivationSheet.Name || "") : "",
    optional_reset: null,
  };
  let failureCode = "";
  let failureMessage = "";
  const fail = (code, message) => {
    if (failureCode) return;
    failureCode = code;
    failureMessage = `${code}: ${message}`;
  };
  verifiedFormatOperation(report, warnings, sheet.Name, "freeze_panes", expected.mode, () => {
    try {
      const reset = resetWindowPaneState(sheet);
      diagnostics.before = reset.before;
      diagnostics.after_reset = reset.after_reset;
      diagnostics.optional_reset = reset.optional_reset;
      if (expected.mode === FREEZE_MODE_FIRST_ROW_ONLY) {
        diagnostics.after_select = selectFirstRowFreezeAnchor(sheet);
        reset.window.FreezePanes = true;
      }
      diagnostics.immediate = paneDiagnostics(Application.ActiveWindow);
      if (!freezeStateMatches(diagnostics.immediate, expected)) {
        fail(
          "WPS_FREEZE_IMMEDIATE_READBACK_FAILED",
          `expected ${expected.mode}, actual split_row=${diagnostics.immediate.split_row}, split_column=${diagnostics.immediate.split_column}, freeze=${diagnostics.immediate.freeze}`,
        );
      }
    } catch (error) {
      const reason = String(error && error.message || error);
      const code = reason.startsWith("WPS_FREEZE_SELECTION_FAILED")
        ? "WPS_FREEZE_SELECTION_FAILED"
        : reason.startsWith("WPS_FREEZE_RESET_FAILED")
        ? "WPS_FREEZE_RESET_FAILED"
        : "WPS_FREEZE_APPLY_FAILED";
      fail(code, reason.startsWith(code) ? reason.slice(code.length + 1).trim() : reason);
    }
  }, () => {
    try {
      if (reactivationSheet && String(reactivationSheet.Name || "") !== String(sheet.Name || "")) {
        reactivationSheet.Activate();
      }
      sheet.Activate();
      if (activeSheetName() !== String(sheet.Name || "")) {
        throw new Error(`expected active sheet ${sheet.Name}, actual ${activeSheetName() || "?"}`);
      }
      diagnostics.reactivated = paneDiagnostics(Application.ActiveWindow);
      if (!freezeStateMatches(diagnostics.reactivated, expected)) {
        fail(
          "WPS_FREEZE_REACTIVATION_READBACK_FAILED",
          `expected ${expected.mode}, actual split_row=${diagnostics.reactivated.split_row}, split_column=${diagnostics.reactivated.split_column}, freeze=${diagnostics.reactivated.freeze}`,
        );
      }
    } catch (error) {
      fail("WPS_FREEZE_REACTIVATION_FAILED", String(error && error.message || error));
    }
    const actual = diagnostics.reactivated || diagnostics.immediate || paneDiagnostics(Application.ActiveWindow);
    const verified = !failureCode
      && freezeStateMatches(diagnostics.immediate || {}, expected)
      && freezeStateMatches(diagnostics.reactivated || {}, expected);
    return {
      verified,
      expected,
      actual,
      requested_mode: requestedMode,
      mode: expected.mode,
      before: diagnostics.before,
      after_reset: diagnostics.after_reset,
      after_select: diagnostics.after_select,
      immediate: diagnostics.immediate,
      reactivated: diagnostics.reactivated,
      reactivation_switch_sheet: diagnostics.reactivation_switch_sheet,
      optional_reset: diagnostics.optional_reset,
      expected_frozen_rows: expected.split_row,
      actual_frozen_rows: actual.split_row,
      expected_frozen_columns: 0,
      actual_frozen_columns: actual.split_column,
      error_code: failureCode,
      error_message: failureMessage,
    };
  }, { freeze_summary: true });
}

function normalizeAddress(value) {
  return String(value || "").replace(/\$/g, "").toUpperCase();
}

function applyAutoFilter(sheet, address, warnings, report) {
  const expectedAddress = normalizeAddress(address);
  verifiedFormatOperation(report, warnings, sheet.Name, "auto_filter", expectedAddress || "NONE", () => {
    let current = "";
    try { current = normalizeAddress(sheet.AutoFilter && sheet.AutoFilter.Range && sheet.AutoFilter.Range.Address); } catch (_error) { current = ""; }
    if (current) {
      if ("AutoFilterMode" in sheet) sheet.AutoFilterMode = false;
      else {
        const currentRange = sheet.Range(current);
        if (!currentRange.AutoFilter) throw new Error("Worksheet AutoFilter clear API unavailable");
        currentRange.AutoFilter();
      }
    }
    if (!expectedAddress) return;
    const range = sheet.Range(address);
    if (!range.AutoFilter) throw new Error("Range.AutoFilter API unavailable");
    range.AutoFilter();
  }, () => {
    let actual = "";
    try { actual = normalizeAddress(sheet.AutoFilter && sheet.AutoFilter.Range && sheet.AutoFilter.Range.Address); } catch (_error) { actual = ""; }
    return { verified: actual === expectedAddress, expected: expectedAddress, actual };
  });
}

function rowValues(value) {
  if (Array.isArray(value) && value.length === 1 && Array.isArray(value[0])) return value[0];
  return Array.isArray(value) ? value : [value];
}

function verifySheetSamples(sheet, sheetDto, warnings, report) {
  for (const sample of sheetDto.verification_samples || []) {
    verifiedFormatOperation(report, warnings, sheet.Name, "sample_data", sample.range, () => {}, () => {
      const expected = sample.expected_values || [];
      const actual = rowValues(sheet.Range(sample.range).Value2);
      return { verified: JSON.stringify(actual) === JSON.stringify(expected), expected, actual };
    });
    for (const formatCell of sample.format_cells || []) {
      if (!formatCell || !formatCell.range || !formatCell.expected) continue;
      verifiedFormatOperation(
        report,
        warnings,
        sheet.Name,
        "sample_data",
        formatCell.range,
        () => {},
        () => sampleFormatReadback(
          sheet.Range(formatCell.range),
          formatCell.expected,
          formatCell.expected_display_text,
        ),
      );
    }
  }
}

function applySheetFormatting(sheet, sheetDto, warnings, report) {
  const runs = sheetDto.format_runs || [];
  if (runs.length > MAX_FORMAT_RUNS_PER_SHEET) {
    addFormatWarning(warnings, sheet.Name, "format_runs", new Error(`format run count ${runs.length} exceeds ${MAX_FORMAT_RUNS_PER_SHEET}`));
    return;
  }
  const targetRange = prepareFormatTarget(sheet, sheetDto, warnings);
  applyAllBorders(sheet, sheetDto, warnings, report);
  for (const run of runs) applyFormatRun(sheet, run, warnings, report);
  applyMerges(sheet, sheetDto, warnings, report);
  return targetRange;
}

function applySheetLayout(sheet, sheetDto, targetRange, warnings, report) {
  applyRowHeights(sheet, sheetDto, targetRange, warnings, report);
  applyAutoFilter(sheet, sheetDto.auto_filter, warnings, report);
  verifySheetSamples(sheet, sheetDto, warnings, report);
}

function applyBusinessFormatting(sheetDtos, warnings, beforeLayout) {
  const report = createFormatResults();
  const formatRunCounts = { font: 0, fill: 0, number_format: 0, alignment: 0, border: 0 };
  const targets = [];
  for (const sheetDto of sheetDtos || []) {
    const sheet = findSheet(sheetDto.sheet_name);
    if (!sheet) {
      addFormatWarning(warnings, sheetDto.sheet_name, "format_sheet", new Error("worksheet unavailable"));
      continue;
    }
    for (const run of sheetDto.format_runs || []) {
      for (const featureName of Object.keys(formatRunCounts)) {
        const value = run[featureName];
        if (value && (typeof value !== "object" || Object.keys(value).length)) {
          formatRunCounts[featureName] += 1;
        }
      }
    }
    try {
      const targetRange = applySheetFormatting(sheet, sheetDto, warnings, report);
      targets.push({ sheet, sheetDto, targetRange });
    } catch (error) {
      addFormatWarning(warnings, sheet.Name, "format_sheet", error);
    }
  }
  if (typeof beforeLayout === "function") beforeLayout();
  for (const target of targets) {
    try {
      applySheetLayout(target.sheet, target.sheetDto, target.targetRange, warnings, report);
    } catch (error) {
      addFormatWarning(warnings, target.sheet.Name, "format_layout", error);
    }
  }
  const finalized = finalizeFormatResults(report);
  for (const [featureName, count] of Object.entries(formatRunCounts)) {
    finalized[featureName].format_run_count = count;
  }
  return finalized;
}

function applyWorkbookFreezeLayout(sheetDtos, warnings, report) {
  const targets = [];
  for (const sheetDto of sheetDtos || []) {
    const sheet = findSheet(sheetDto.sheet_name);
    if (!sheet) {
      addFormatWarning(warnings, sheetDto.sheet_name, "freeze_panes", new Error("worksheet unavailable"));
      continue;
    }
    targets.push({ sheet, sheetDto });
  }
  for (let index = 0; index < targets.length; index += 1) {
    const target = targets[index];
    const reactivationSheet = targets.length > 1
      ? targets[(index + 1) % targets.length].sheet
      : null;
    applyFreezeMode(target.sheet, target.sheetDto, reactivationSheet, warnings, report);
  }
  const result = report.freeze_panes;
  result.status = result.failed_count || result.warning_count
    ? "SUCCESS_WITH_WARNINGS"
    : "SUCCESS";
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
  const verification_samples = (sheetDto.verification_samples || []).map((sample) => {
    const row = Number(sample && sample.row);
    if (!Number.isInteger(row) || row < 1 || row > cells.length) return sample;
    return {
      ...sample,
      expected_values: cells[row - 1].slice(0, Number(sheetDto.column_count) || cells[row - 1].length),
    };
  });
  return { ...sheetDto, sync_mode: syncMode, cells, verification_samples };
}

function writeStableSheet(sheetDto, previousManaged) {
  const sheet = ensureSheet(sheetDto.sheet_name);
  const values = sheetDto.cells || [];
  let managedRange = null;
  if (sheetDto.sync_mode === "APPEND_SNAPSHOT") {
    if (values.length) sheet.Range(`A1:A${values.length}`).EntireRow.Insert();
    if (values.length) sheet.Range("A1").Resize(values.length, sheetDto.column_count).Value2 = values;
  } else if (sheetDto.sync_mode === "FULL_REPLACE") {
    managedRange = clearFullReplaceTarget(sheet, sheetDto, previousManaged);
    if (values.length) sheet.Range("A1").Resize(values.length, sheetDto.column_count).Value2 = values;
  }
  return { written_rows: values.length, managed_range: managedRange, format_verification: { checked: false } };
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

function applyBusinessSheetTabColors(sheetDtos, warnings, report) {
  let applied = 0;
  for (const sheetDto of sheetDtos || []) {
    if (!sheetDto.tab_color) continue;
    const sheet = findSheet(sheetDto.sheet_name);
    if (!sheet) continue;
    const success = verifiedFormatOperation(
      report,
      warnings,
      sheet.Name,
      "sheet_tab_color",
      "Tab.Color",
      () => { sheet.Tab.Color = toWpsColor(sheetDto.tab_color); },
      () => {
        const expected = toWpsColor(sheetDto.tab_color);
        const actual = sheet.Tab.Color;
        return { verified: Number(actual) === Number(expected), expected, actual };
      },
    );
    if (success) applied += 1;
  }
  return applied;
}

function dimensionValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? Number(number.toFixed(2)) : null;
}

function keepDimensionExample(examples, example) {
  if (examples.length >= 20) return;
  if (!example.verified || examples.length < 5) examples.push(example);
}

function readWidthPoints(column) {
  try {
    return dimensionValue(column.Width);
  } catch (_error) {
    return null;
  }
}

function applyBusinessColumnWidths(sheetDtos, warnings) {
  const sheetResults = {};
  const examples = [];
  const items = [];
  let attempted = 0;
  let verified = 0;
  let failed = 0;
  let applied = 0;
  let explicitApplied = 0;
  let autoFitApplied = 0;
  let clamped = 0;
  let durationMs = 0;
  for (const sheetDto of sheetDtos || []) {
    const widths = Object.entries(sheetDto.column_widths || {});
    const widthsByColumn = Object.fromEntries(widths.map(([column, width]) => [String(column), width]));
    const autoFitColumns = [...new Set((sheetDto.auto_fit_columns || []).map((column) => String(column)))];
    const autoFitSet = new Set(autoFitColumns);
    const operationColumns = [...new Set([...Object.keys(widthsByColumn), ...autoFitColumns])];
    const operations = operationColumns.map((column) => ({
      column,
      mode: autoFitSet.has(column)
        ? widthsByColumn[column] === undefined
          ? "AUTO_FIT"
          : "AUTO_FIT_WITH_LOCAL_MIN"
        : "EXPLICIT",
      width: widthsByColumn[column] === undefined ? null : widthsByColumn[column],
      layout: (sheetDto.column_layouts || {})[column] || {},
    }));
    const startedAt = Date.now();
    const sheetName = String(sheetDto.sheet_name || "");
    const sheetExamples = [];
    const sheetItems = [];
    let sheetVerified = 0;
    let sheetFailed = 0;
    let sheetApplied = 0;
    let sheetClamped = 0;
    attempted += operations.length;
    const sheet = findSheet(sheetName);
    if (!sheet && operations.length) {
      sheetFailed = operations.length;
      failed += operations.length;
      addFormatWarning(warnings, sheetName, "column_width", new Error("worksheet unavailable"));
      for (const operation of operations) {
        const { column, mode, width: widthValue, layout } = operation;
        const range = `${column}:${column}`;
        const item = {
          sheet_name: sheetName,
          column: String(column),
          range,
          mode,
          layout_type: String(layout.layout_type || "normal"),
          local_workbook_width: dimensionValue(widthValue),
          auto_fit_width: null,
          requested_width: null,
          before_column_width: null,
          remote_column_width: null,
          before_width_points: null,
          remote_width_points: null,
          difference: null,
          physical_width_change_points: null,
          read_back: false,
          applied: false,
          clamped: false,
          verified: false,
          classification: "WPS_COLUMN_WIDTH_APPLY_MISMATCH",
          reason: "worksheet unavailable",
        };
        sheetItems.push(item);
        items.push(item);
        keepDimensionExample(sheetExamples, item);
      }
    } else if (sheet) {
      for (const operation of operations) {
        const { column, mode, width: widthValue, layout } = operation;
        const localWidth = widthValue === null || widthValue === undefined ? null : Number(widthValue);
        const expected = mode === "EXPLICIT" ? localWidth : null;
        const range = `${column}:${column}`;
        const item = {
          sheet_name: sheet.Name,
          column: String(column),
          range,
          mode,
          layout_type: String(layout.layout_type || "normal"),
          layout_min_width: dimensionValue(layout.min_width),
          layout_max_width: dimensionValue(layout.max_width),
          local_workbook_width: dimensionValue(localWidth),
          auto_fit_width: null,
          requested_width: dimensionValue(expected),
          before_column_width: null,
          remote_column_width: null,
          before_width_points: null,
          remote_width_points: null,
          difference: null,
          physical_width_change_points: null,
          read_back: false,
          applied: false,
          clamped: false,
          verified: false,
          classification: "WPS_COLUMN_WIDTH_APPLY_MISMATCH",
          reason: "",
        };
        if (mode === "EXPLICIT" && (!Number.isFinite(expected) || expected <= 0)) {
          sheetFailed += 1;
          failed += 1;
          item.classification = "WPS_COLUMN_WIDTH_PAYLOAD_INVALID";
          item.reason = "invalid column width";
          addFormatWarning(warnings, sheet.Name, "column_width", new Error("invalid column width"), range);
          sheetItems.push(item);
          items.push(item);
          keepDimensionExample(sheetExamples, item);
          continue;
        }
        try {
          if (!sheet.Columns || !sheet.Columns.Item) throw new Error("Worksheet.Columns.Item API unavailable");
          const targetColumn = sheet.Columns.Item(String(column));
          item.before_column_width = dimensionValue(targetColumn.ColumnWidth);
          item.before_width_points = readWidthPoints(targetColumn);
          if (mode.startsWith("AUTO_FIT")) {
            const columnRange = sheet.Range(range);
            if (columnRange.Columns && columnRange.Columns.AutoFit) columnRange.Columns.AutoFit();
            else if (targetColumn.AutoFit) targetColumn.AutoFit();
            else throw new Error("Columns.AutoFit API unavailable");
            const fitted = Number(targetColumn.ColumnWidth);
            if (!Number.isFinite(fitted) || fitted <= 0) throw new Error("Columns.AutoFit readback unavailable");
            item.auto_fit_width = dimensionValue(fitted);
            const minimum = Number(layout.min_width || sheetDto.auto_fit_min_width || 8);
            const maximum = Number(layout.max_width || sheetDto.auto_fit_max_width || 60);
            const desiredBeforeClamp = Math.max(
              Number.isFinite(localWidth) && localWidth > 0 ? localWidth : 0,
              fitted,
              minimum,
            );
            const desired = Math.min(Math.max(desiredBeforeClamp, minimum), maximum);
            item.clamped = Math.abs(desired - desiredBeforeClamp) > COLUMN_WIDTH_TOLERANCE;
            item.requested_width = dimensionValue(desired);
            targetColumn.ColumnWidth = desired;
            if (layout.wrap_text) {
              const dataStartRow = sheetDto.logical_sheet_key === "ap_online_history_overview" ? 4 : 2;
              const dataEndRow = Math.max(Number(sheetDto.row_count) || 0, dataStartRow);
              if (dataEndRow >= dataStartRow) sheet.Range(`${column}${dataStartRow}:${column}${dataEndRow}`).WrapText = true;
            }
          } else {
            targetColumn.ColumnWidth = expected;
          }
          item.applied = true;
          sheetApplied += 1;
          applied += 1;
          if (mode.startsWith("AUTO_FIT")) autoFitApplied += 1;
          else explicitApplied += 1;
          if (item.clamped) { sheetClamped += 1; clamped += 1; }
          item.remote_column_width = dimensionValue(targetColumn.ColumnWidth);
          item.remote_width_points = readWidthPoints(targetColumn);
          item.read_back = item.remote_column_width !== null;
          const requestedWidth = Number(item.requested_width);
          item.difference = item.remote_column_width === null || !Number.isFinite(requestedWidth)
            ? null
            : dimensionValue(Math.abs(item.remote_column_width - requestedWidth));
          item.physical_width_change_points = item.before_width_points === null || item.remote_width_points === null
            ? null
            : dimensionValue(item.remote_width_points - item.before_width_points);
          const matches = item.remote_column_width !== null
            && Number.isFinite(requestedWidth)
            && Math.abs(item.remote_column_width - requestedWidth) <= COLUMN_WIDTH_TOLERANCE;
          item.verified = matches;
          item.classification = matches
            ? mode.startsWith("AUTO_FIT") ? "WPS_COLUMN_WIDTH_AUTOFIT_VERIFIED" : "WPS_COLUMN_WIDTH_VALUE_VERIFIED"
            : "WPS_COLUMN_WIDTH_APPLY_MISMATCH";
          item.reason = matches
            ? mode.startsWith("AUTO_FIT") ? "Columns.AutoFit plus local minimum readback matched" : "ColumnWidth write/readback matched"
            : `readback mismatch: mode=${mode}, expected=${String(item.requested_width)}, actual=${String(item.remote_column_width)}`;
          if (matches) {
            sheetVerified += 1;
            verified += 1;
          } else {
            sheetFailed += 1;
            failed += 1;
            addFormatWarning(warnings, sheet.Name, "column_width", new Error(item.reason), range);
          }
        } catch (error) {
          sheetFailed += 1;
          failed += 1;
          item.reason = String(error && error.message || error).slice(0, 300);
          addFormatWarning(warnings, sheet.Name, "column_width", error, range);
        }
        sheetItems.push(item);
        items.push(item);
        keepDimensionExample(sheetExamples, item);
      }
    }
    const sheetDurationMs = Date.now() - startedAt;
    durationMs += sheetDurationMs;
    for (const example of sheetExamples) keepDimensionExample(examples, example);
    sheetResults[sheetName] = {
      attempted_count: operations.length,
      explicit_count: widths.length,
      auto_fit_count: autoFitColumns.length,
      verified_count: sheetVerified,
      failed_count: sheetFailed,
      expected_count: operations.length,
      applied_count: sheetApplied,
      clamped_count: sheetClamped,
      dimension_ms: sheetDurationMs,
      examples: sheetExamples,
      items: sheetItems,
    };
  }
  return { attempted_count: attempted, verified_count: verified, failed_count: failed, expected_count: attempted, applied_count: applied, explicit_applied_count: explicitApplied, auto_fit_applied_count: autoFitApplied, clamped_count: clamped, dimension_ms: durationMs, examples, items, sheets: sheetResults };
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
  const formatSheets = [];
  const managedRanges = readManagedRanges(binding.meta);
  const formatMirrorEnabled = FORMAT_MIRROR_ENABLED && args.format_mirror_enabled === true;
  try {
    for (const sheet of sheets) {
      const runtimeSheet = materializeRuntimeSheet(sheet, args, targetSyncTime);
      const skipRepeatedPrepend = repeatedPrependBatch
        && sheet.sync_mode === "PREPEND_SNAPSHOT";
      const dataWriteStartedAt = Date.now();
      const result = skipRepeatedPrepend
        ? { written_rows: 0, format_verification: { checked: false }, deduplicated: true }
        : writeStableSheet(runtimeSheet, managedRanges[String(sheet.sheet_name || "")]);
      if (result.managed_range) managedRanges[String(sheet.sheet_name || "")] = result.managed_range;
      if (formatMirrorEnabled && !skipRepeatedPrepend) formatSheets.push(runtimeSheet);
      if (!skipRepeatedPrepend && sheet.sync_mode === "PREPEND_SNAPSHOT") {
        binding.meta = updateBindingMetadata({
          last_prepend_target_batch_id: String(args.target_batch_id || ""),
        });
      }
      writtenRows += result.written_rows;
      writtenSheets += 1;
      sheetResults.push({ sheet_name: sheet.sheet_name, sync_mode: sheet.sync_mode, success: true, written_rows: result.written_rows, deduplicated: !!result.deduplicated, column_count: Number(sheet.column_count) || 0, column_width_count: Object.keys(sheet.column_widths || {}).length, auto_fit_column_count: (sheet.auto_fit_columns || []).length, data_write_ms: Date.now() - dataWriteStartedAt, dimension_ms: 0, format_ms: 0, format_run_count: (sheet.format_runs || []).length, format_verification: result.format_verification });
    }
  } catch (error) {
    try {
      binding.meta = updateBindingMetadata({ managed_ranges_json: JSON.stringify(managedRanges) });
    } catch (_metadataError) { /* Preserve the original sheet write failure. */ }
    return response({ success: false, error_code: "WPS_SHEET_WRITE_FAILED", failed_sheet: sheets[writtenSheets] && sheets[writtenSheets].sheet_name || "", failed_operation: "WRITE_VALUES", written_sheet_count: writtenSheets, written_row_count: writtenRows, message: String(error && error.message || error).slice(0, 500), runtime_error_name: String(error && error.name || "Error"), runtime_error_stack: String(error && error.stack || "").slice(0, 2048), binding_status: "BOUND" });
  }
  try {
    binding.meta = updateBindingMetadata({ managed_ranges_json: JSON.stringify(managedRanges) });
  } catch (error) {
    addFormatWarning(formatWarnings, META_SHEET, "managed_ranges", error);
  }
  const columnWidthEnabled = args.column_width_enabled === true;
  let columnWidthResult = { attempted_count: 0, verified_count: 0, failed_count: 0, applied_count: 0, expected_count: 0, dimension_ms: 0, examples: [], items: [], sheets: {} };
  let mirroredFormatResults = createFormatResults();
  if (formatMirrorEnabled) {
    try {
      mirroredFormatResults = applyBusinessFormatting(formatSheets, formatWarnings, () => {
        if (!columnWidthEnabled) return;
        try {
          columnWidthResult = applyBusinessColumnWidths(sheets, formatWarnings);
        } catch (error) {
          addFormatWarning(formatWarnings, "_NetConsoleColumnWidths", "column_width", error);
        }
      });
    } catch (error) {
      addFormatWarning(formatWarnings, "_NetConsoleFormats", "format_mirror", error);
      mirroredFormatResults = finalizeFormatResults(mirroredFormatResults);
    }
  } else {
    if (columnWidthEnabled) {
      try {
        columnWidthResult = applyBusinessColumnWidths(sheets, formatWarnings);
      } catch (error) {
        addFormatWarning(formatWarnings, "_NetConsoleColumnWidths", "column_width", error);
      }
    }
    for (const feature of Object.values(mirroredFormatResults)) feature.status = "NOT_ENABLED";
  }
  for (const sheetResult of sheetResults) {
    const columnDimension = columnWidthResult.sheets[sheetResult.sheet_name];
    sheetResult.column_width_result = columnDimension || { attempted_count: 0, verified_count: 0, failed_count: 0, examples: [] };
    sheetResult.dimension_ms = Number(columnDimension && columnDimension.dimension_ms || 0);
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
  mirroredFormatResults.sheet_order = {
    status: "SUCCESS",
    attempted_count: 1,
    applied_count: 1,
    read_back_count: 1,
    verified_count: 1,
    failed_count: 0,
    warning_count: 0,
    examples: [{
      sheet_name: "_NetConsoleWorkbook",
      range: "Worksheets",
      expected: sheetOrderVerification.expected,
      actual: sheetOrderVerification.actual,
      verified: true,
    }],
  };
  const appliedTabColorCount = args.sheet_tab_color_enabled === true
    ? applyBusinessSheetTabColors(sheets, formatWarnings, mirroredFormatResults)
    : 0;
  if (args.sheet_tab_color_enabled !== true) {
    mirroredFormatResults.sheet_tab_color.status = "NOT_ENABLED";
  } else {
    mirroredFormatResults.sheet_tab_color.status = mirroredFormatResults.sheet_tab_color.failed_count || mirroredFormatResults.sheet_tab_color.warning_count
      ? "SUCCESS_WITH_WARNINGS"
      : "SUCCESS";
  }
  if (formatMirrorEnabled) applyWorkbookFreezeLayout(sheets, formatWarnings, mirroredFormatResults);
  try {
    binding.meta = updateBindingMetadata({
      last_sync_at: new Date().toISOString(),
      last_sync_revision: String(args.snapshot_revision || ""),
      last_target_batch_id: String(args.target_batch_id || ""),
      managed_ranges_json: JSON.stringify(managedRanges),
    });
  } catch (error) {
    addFormatWarning(formatWarnings, META_SHEET, "sync_metadata", error);
  }
  const publicWarnings = formatWarnings.map(({ key, ...warning }) => warning);
  const columnWidthWarnings = publicWarnings.filter((warning) => warning.feature === "column_width");
  const formatResults = {
    column_width: {
      status: columnWidthEnabled ? (columnWidthResult.failed_count || columnWidthWarnings.length ? "SUCCESS_WITH_WARNINGS" : "SUCCESS") : "NOT_ENABLED",
      attempted_count: columnWidthResult.attempted_count,
      verified_count: columnWidthResult.verified_count,
      failed_count: columnWidthResult.failed_count,
      applied_count: columnWidthResult.applied_count,
      explicit_applied_count: columnWidthResult.explicit_applied_count,
      auto_fit_applied_count: columnWidthResult.auto_fit_applied_count,
      clamped_count: columnWidthResult.clamped_count,
      expected_count: columnWidthResult.expected_count,
      warning_count: columnWidthWarnings.length,
      duration_ms: columnWidthResult.dimension_ms,
      examples: columnWidthResult.examples,
    },
    ...mirroredFormatResults,
  };
  return response({ success: true, status: publicWarnings.length ? "SUCCESS_WITH_WARNINGS" : "SUCCESS", ...bindingDiagnostics(args, binding.meta), parent_batch_id: args.parent_batch_id, target_batch_id: args.target_batch_id, site_id: args.site_id, site_name: args.site_name, business_key: args.business_key, snapshot_revision: args.snapshot_revision, snapshot_sha256: args.snapshot_sha256, target_sync_executed_at: targetSyncTime, idempotent_prepend_replay: repeatedPrependBatch, written_sheet_count: writtenSheets, written_row_count: writtenRows, written_object_count: sheets.length, sheet_order_verified: true, expected_sheet_order: sheetOrderVerification.expected, actual_sheet_order: sheetOrderVerification.actual, ...systemSheetResult, sheet_tab_color_enabled: args.sheet_tab_color_enabled === true, applied_tab_color_count: appliedTabColorCount, column_width_enabled: columnWidthEnabled, applied_column_width_count: columnWidthResult.applied_count, column_width_result: columnWidthResult, dimension_ms: columnWidthResult.dimension_ms, format_results: formatResults, format_mirror_enabled: formatMirrorEnabled, format_warning_count: publicWarnings.length, format_warnings: publicWarnings, sheets: sheetResults });
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

function columnWidthProbe(args) {
  const sheetName = "_NetConsoleSyncTest";
  const expected = { A: 8, B: 15, C: 25, D: 40 };
  const actual = {};
  try {
    const sheet = ensureSheet(sheetName);
    sheet.Range("A1").Resize(2, 4).Value2 = [
      ["A = 8", "B = 15", "C = 25", "D = 40"],
      ["列宽探针", "列宽探针", "列宽探针", "列宽探针"],
    ];
    for (const [column, width] of Object.entries(expected)) {
      if (!sheet.Columns || !sheet.Columns.Item) throw new Error("Worksheet.Columns.Item API unavailable");
      sheet.Columns.Item(column).ColumnWidth = width;
    }
    for (const [column, width] of Object.entries(expected)) {
      const readback = Number(probeScalarValue(sheet.Columns.Item(column).ColumnWidth));
      actual[column] = Number.isFinite(readback) ? Number(readback.toFixed(2)) : null;
      if (!Number.isFinite(readback) || Math.abs(readback - width) > COLUMN_WIDTH_TOLERANCE) {
        throw new Error(`${column} column width readback mismatch: ${String(readback)}`);
      }
    }
    let probeSheetVisible = true;
    try {
      if ("Visible" in sheet) sheet.Visible = true;
    } catch (_error) {
      probeSheetVisible = false;
    }
    return response({
      success: true,
      status: "SUCCESS",
      error_code: "",
      message: "列宽能力探针通过",
      ...bindingDiagnostics(args),
      column_width_verified: true,
      expected_column_widths: expected,
      actual_column_widths: actual,
      probe_sheet_visible: probeSheetVisible,
      probe_sheet: sheetName,
      probe_id: args.probe_id,
    });
  } catch (error) {
    return response({ success: false, status: "FAILED", error_code: "WPS_COLUMN_WIDTH_VERIFY_FAILED", failed_operation: "COLUMN_WIDTH_PROBE", message: String(error && error.message || error).slice(0, 500), runtime_error_name: String(error && error.name || "Error"), runtime_error_stack: String(error && error.stack || "").slice(0, 2048), ...bindingDiagnostics(args), column_width_verified: false, expected_column_widths: expected, actual_column_widths: actual, probe_sheet: sheetName, probe_id: args.probe_id });
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
  if (args.operation === "column_width_probe") return columnWidthProbe(args);
  if (args.operation === "sync_test_sheet") return syncTestSheet(args);
  if (args.operation === "sync_trackside_ap_business") return sync(args);
  return response({ success: false, error_code: "OPERATION_UNSUPPORTED", message: "unsupported operation" });
}

// Explicit execution entry point. Confirm the returned JSON in the WPS editor
// before using the newly copied webhook in production.
return main();
