// NetConsole WPS_STANDARD_SPREADSHEET AirScript protocol v2.
// Publish this script in the ordinary online spreadsheet document.
// The exact workbook API names are kept in these small helpers so a WPS
// runtime upgrade does not change the NetConsole payload contract.
const PROTOCOL_VERSION = 2;
const SCRIPT_VERSION = "2.1.0-standard";
const DEPLOYMENT_ID = "trackside-ap-standard-2.1.0";
const DOCUMENT_ID = "549847228994";
const TARGET_TYPE = "WPS_STANDARD_SPREADSHEET";
const TARGET_CODE = "wps_standard_spreadsheet";
const RUNTIME_CAPABILITY = "DEPLOYMENT_PENDING";

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
  // The probe is deliberately side-effect free and reads only Context.argv.
  return response({ success: true, objects: [], capabilities: { supports_sheets: true, supports_tables: false, supports_records: false, supports_insert_rows: true, supports_batch_write: true, max_payload_bytes: 20 * 1024 * 1024, max_rows_per_request: 5000 }, verification: "CONNECTION_PROBE_ONLY" });
}

function ensureSheet(name) {
  const book = workbook();
  const sheets = book.Sheets || book.Worksheets;
  for (let index = 0; index < sheets.Count; index += 1) if (String(sheets.Item(index + 1).Name) === name) return sheets.Item(index + 1);
  const sheet = sheets.Add();
  if (sheet && "Name" in sheet) sheet.Name = name;
  return sheet;
}

function writeSheet(sheetDto) {
  const sheet = ensureSheet(sheetDto.sheet_name);
  const values = sheetDto.cells || [];
  if (sheetDto.sync_mode === "APPEND_SNAPSHOT") {
    sheet.Rows.Insert(1, values.length);
    sheet.Range("A1").Resize(values.length, sheetDto.column_count).Value = values;
  } else if (sheetDto.sync_mode === "FULL_REPLACE") {
    const used = sheet.UsedRange;
    if (used && used.ClearContents) used.ClearContents();
    if (values.length) sheet.Range("A1").Resize(values.length, sheetDto.column_count).Value = values;
  }
  return values.length;
}

function sync(payload) {
  const args = payload;
  if (args.protocol_version !== PROTOCOL_VERSION || args.target_type !== TARGET_TYPE) throw new Error("protocol or target type mismatch");
  const sheets = args.workbook && args.workbook.sheets ? args.workbook.sheets : [];
  let writtenRows = 0;
  for (const sheet of sheets) writtenRows += writeSheet(sheet);
  return response({ success: true, parent_batch_id: args.parent_batch_id, target_batch_id: args.target_batch_id, site_id: args.site_id, business_key: args.business_key, snapshot_revision: args.snapshot_revision, snapshot_sha256: args.snapshot_sha256, written_row_count: writtenRows, written_object_count: sheets.length, sheets: sheets.map((sheet) => ({ sheet_name: sheet.sheet_name, sync_mode: sheet.sync_mode, success: true, written_rows: sheet.row_count })) });
}

function main() {
  const args = argv();
  if (args.operation === "connection_test") return connectionTest();
  if (args.operation === "sync_trackside_ap_business") return sync(args);
  return response({ success: false, error_code: "OPERATION_UNSUPPORTED", message: "unsupported operation" });
}

// Explicit execution entry point. Confirm the returned JSON in the WPS editor
// before using the newly copied webhook in production.
return main();
