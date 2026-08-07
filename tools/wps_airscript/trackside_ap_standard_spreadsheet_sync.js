// NetConsole WPS_STANDARD_SPREADSHEET AirScript protocol v2.
// Publish this script in the ordinary online spreadsheet document.
// The exact workbook API names are kept in these small helpers so a WPS
// runtime upgrade does not change the NetConsole payload contract.
const PROTOCOL_VERSION = 2;
const SCRIPT_VERSION = "2.2.0-standard";
const DEPLOYMENT_ID = "trackside-ap-standard-2.2.0";
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
  return JSON.stringify({ protocol_version: PROTOCOL_VERSION, script_version: SCRIPT_VERSION, deployment_id: DEPLOYMENT_ID, document_id: DOCUMENT_ID, target_type: TARGET_TYPE, target_code: TARGET_CODE, runtime_capability: RUNTIME_CAPABILITY, ...value });
}

function workbook() {
  if (typeof Application === "undefined") throw new Error("WPS Application API unavailable");
  return Application.ActiveWorkbook || Application.Workbook || Application;
}

function sheetNames() {
  const book = workbook();
  const sheets = book.Sheets || book.Worksheets || [];
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
  const book = workbook();
  const sheets = book.Sheets || book.Worksheets;
  for (let index = 0; index < sheets.Count; index += 1) if (String(sheets.Item(index + 1).Name) === name) return sheets.Item(index + 1);
  const sheet = sheets.Add();
  if (sheet && "Name" in sheet) sheet.Name = name;
  return sheet;
}

function findSheet(name) {
  const book = workbook();
  const sheets = book.Worksheets || book.Sheets;
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

function writeSheet(sheetDto) {
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
  return values.length;
}

function sync(payload) {
  const args = payload;
  if (args.protocol_version !== PROTOCOL_VERSION || args.target_type !== TARGET_TYPE) return response({ success: false, error_code: "WPS_PROTOCOL_MISMATCH", message: "protocol or target type mismatch" });
  const binding = assertBinding(args);
  if (!binding.ok) return binding.error;
  const sheets = args.workbook && args.workbook.sheets ? args.workbook.sheets : [];
  let writtenRows = 0;
  let writtenSheets = 0;
  try {
    for (const sheet of sheets) { writtenRows += writeSheet(sheet); writtenSheets += 1; }
  } catch (error) {
    return response({ success: false, error_code: "WPS_SHEET_WRITE_FAILED", failed_sheet: sheets[writtenSheets] && sheets[writtenSheets].sheet_name || "", failed_operation: "WRITE_VALUES", written_sheet_count: writtenSheets, written_row_count: writtenRows, message: String(error && error.message || error).slice(0, 500), runtime_error_name: String(error && error.name || "Error"), runtime_error_stack: String(error && error.stack || "").slice(0, 2048), binding_status: "BOUND" });
  }
  return response({ success: true, binding_status: "BOUND", binding_id: args.binding_id, parent_batch_id: args.parent_batch_id, target_batch_id: args.target_batch_id, site_id: args.site_id, site_name: args.site_name, business_key: args.business_key, snapshot_revision: args.snapshot_revision, snapshot_sha256: args.snapshot_sha256, written_sheet_count: writtenSheets, written_row_count: writtenRows, written_object_count: sheets.length, sheets: sheets.map((sheet) => ({ sheet_name: sheet.sheet_name, sync_mode: sheet.sync_mode, success: true, written_rows: sheet.row_count })) });
}

function runtimeWriteProbe(args) {
  const sheet = ensureSheet(PROBE_SHEET);
  const values = [["NetConsole runtime probe", args.probe_id], [new Date().toISOString(), "2x2"]];
  try {
    sheet.Range("A1").Resize(2, 2).Value2 = values;
    const echoed = sheet.Range("A1").Resize(2, 2).Value2;
    const passed = JSON.stringify(echoed) === JSON.stringify(values);
    return response({ success: passed, error_code: passed ? "" : "WPS_RUNTIME_PROBE_VERIFY_FAILED", message: passed ? "运行时写入探针通过" : "二维数组写后读取不一致", binding_status: readBinding() ? "BOUND" : "UNBOUND", runtime_capability: passed ? "VERIFIED" : "DEPLOYMENT_PENDING", probe_sheet: PROBE_SHEET, probe_id: args.probe_id });
  } catch (error) {
    return response({ success: false, error_code: "WPS_RUNTIME_PROBE_FAILED", message: String(error && error.message || error).slice(0, 500), runtime_error_name: String(error && error.name || "Error"), runtime_error_stack: String(error && error.stack || "").slice(0, 2048), binding_status: readBinding() ? "BOUND" : "UNBOUND", runtime_capability: "DEPLOYMENT_PENDING" });
  }
}

function main() {
  const args = argv();
  if (args.operation === "connection_test") return connectionTest();
  if (args.operation === "runtime_write_probe") return runtimeWriteProbe(args);
  if (args.operation === "sync_trackside_ap_business") return sync(args);
  return response({ success: false, error_code: "OPERATION_UNSUPPORTED", message: "unsupported operation" });
}

// Explicit execution entry point. Confirm the returned JSON in the WPS editor
// before using the newly copied webhook in production.
return main();
