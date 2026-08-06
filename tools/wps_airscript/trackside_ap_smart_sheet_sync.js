// NetConsole WPS_SMART_SHEET AirScript protocol v2.
// This is intentionally a record/batch adapter, not a cell-copy variant.
const PROTOCOL_VERSION = 2;
const SCRIPT_VERSION = "2.0.0-smart";
const DOCUMENT_ID = "cbRdGQdb10R9";
const TARGET_TYPE = "WPS_SMART_SHEET";
const SYSTEM_FIELDS = ["_NC_SITE_ID", "_NC_BUSINESS_KEY", "_NC_TARGET_CODE", "_NC_LOGICAL_SHEET_KEY", "_NC_BATCH_ID", "_NC_REVISION", "_NC_SNAPSHOT_SHA256", "_NC_ROW_KEY", "_NC_ROW_ORDER", "_NC_SYNCED_AT", "_NC_MANAGED"];

function argv() {
  const value = (typeof Context !== "undefined" && Context.argv) || {};
  return value.Context && value.Context.argv ? value.Context.argv : value;
}

function response(value) {
  return JSON.stringify({ protocol_version: PROTOCOL_VERSION, script_version: SCRIPT_VERSION, document_id: DOCUMENT_ID, target_type: TARGET_TYPE, ...value });
}

function tables() {
  if (typeof Application === "undefined") throw new Error("WPS Application API unavailable");
  const book = Application.ActiveWorkbook || Application.Workbook || Application;
  return book.Tables || book.DataTables || [];
}

function connectionTest() {
  const collection = tables();
  const objects = [];
  for (let index = 0; index < collection.Count; index += 1) objects.push({ table_name: String(collection.Item(index + 1).Name || "") });
  return response({ success: true, document_name: String((Application.ActiveWorkbook || Application.Workbook || Application).Name || ""), objects, capabilities: { supports_sheets: false, supports_tables: true, supports_records: true, supports_batch_write: true, supports_batch_update: true, supports_conditional_delete: true, supports_views: true, supports_hidden_fields: true, max_payload_bytes: 20 * 1024 * 1024, max_records_per_request: 500 } });
}

function tableFor(sheetDto) {
  const collection = tables();
  for (let index = 0; index < collection.Count; index += 1) if (String(collection.Item(index + 1).Name) === sheetDto.sheet_name) return collection.Item(index + 1);
  return collection.Add(sheetDto.sheet_name);
}

function managedRecord(sheetDto, row, rowOrder, args) {
  const values = {};
  (sheetDto.cells[0] || []).forEach((field, index) => { values[String(field || `column_${index + 1}`)] = row[index]; });
  return { ...values, _NC_SITE_ID: args.site_id, _NC_BUSINESS_KEY: args.business_key, _NC_TARGET_CODE: args.target_code, _NC_LOGICAL_SHEET_KEY: sheetDto.logical_sheet_key, _NC_BATCH_ID: args.target_batch_id, _NC_REVISION: args.snapshot_revision, _NC_SNAPSHOT_SHA256: args.snapshot_sha256, _NC_ROW_KEY: `${sheetDto.logical_sheet_key}:${rowOrder}`, _NC_ROW_ORDER: rowOrder, _NC_SYNCED_AT: args.snapshot_generated_at, _NC_MANAGED: true };
}

function sync(payload) {
  if (payload.protocol_version !== PROTOCOL_VERSION || payload.target_type !== TARGET_TYPE) throw new Error("protocol or target type mismatch");
  const sheets = payload.workbook && payload.workbook.sheets ? payload.workbook.sheets : [];
  let written = 0;
  for (const sheetDto of sheets) {
    const table = tableFor(sheetDto);
    const header = sheetDto.cells[0] || [];
    if (table.EnsureFields) table.EnsureFields([...header.map(String), ...SYSTEM_FIELDS]);
    const rows = (sheetDto.cells || []).slice(1).map((row, index) => managedRecord(sheetDto, row, index + 1, payload));
    if (sheetDto.sync_mode === "FULL_REPLACE" && table.DeleteWhere) table.DeleteWhere({ _NC_SITE_ID: payload.site_id, _NC_BUSINESS_KEY: payload.business_key, _NC_TARGET_CODE: payload.target_code, _NC_LOGICAL_SHEET_KEY: sheetDto.logical_sheet_key, _NC_MANAGED: true });
    if (rows.length && table.AddRecords) table.AddRecords(rows);
    written += rows.length;
  }
  return response({ success: true, parent_batch_id: payload.parent_batch_id, target_batch_id: payload.target_batch_id, site_id: payload.site_id, business_key: payload.business_key, snapshot_revision: payload.snapshot_revision, snapshot_sha256: payload.snapshot_sha256, written_row_count: written, written_object_count: sheets.length, objects: sheets.map((sheet) => ({ table_name: sheet.sheet_name, sync_mode: sheet.sync_mode, success: true, written_records: Math.max(0, sheet.row_count - 1) })) });
}

function main() {
  const args = argv();
  if (args.operation === "connection_test") return connectionTest();
  if (args.operation === "sync_trackside_ap_business") return sync(args);
  return response({ success: false, error_code: "OPERATION_UNSUPPORTED", message: "unsupported operation" });
}
