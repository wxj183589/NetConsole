// NetConsole WPS_SMART_SHEET AirScript protocol v2.
// The connection probe is read-only. Production record writes stay disabled
// until the target WPS runtime confirms the official multidimensional APIs.
const PROTOCOL_VERSION = 2;
const SCRIPT_VERSION = "2.1.0-smart";
const DEPLOYMENT_ID = "trackside-ap-smart-2.1.0";
const DOCUMENT_ID = "cbRdGQdb10R9";
const TARGET_TYPE = "WPS_SMART_SHEET";
const TARGET_CODE = "wps_smart_sheet";
const RUNTIME_CAPABILITY = "RUNTIME_UNVERIFIED";
const OFFICIAL_RECORD_API = [
  "Application.Sheet",
  "Application.Field",
  "Application.Record",
  "Application.Record.CreateRecords",
  "Application.Record.DeleteRecords",
];

function argv() {
  const value = (typeof Context !== "undefined" && Context.argv) || {};
  return value.Context && value.Context.argv ? value.Context.argv : value;
}

function response(value) {
  return JSON.stringify({
    protocol_version: PROTOCOL_VERSION,
    script_version: SCRIPT_VERSION,
    deployment_id: DEPLOYMENT_ID,
    document_id: DOCUMENT_ID,
    target_type: TARGET_TYPE,
    target_code: TARGET_CODE,
    runtime_capability: RUNTIME_CAPABILITY,
    ...value,
  });
}

function connectionTest() {
  // This path reads only Context.argv. It never creates sheets, fields or
  // records and never deletes or updates existing document data.
  return response({
    success: true,
    objects: [],
    capabilities: {
      supports_sheets: false,
      supports_tables: true,
      supports_records: true,
      supports_batch_write: true,
      supports_batch_update: true,
      supports_conditional_delete: true,
      supports_views: true,
      supports_hidden_fields: true,
      max_payload_bytes: 20 * 1024 * 1024,
      max_records_per_request: 500,
    },
    official_api_surface: OFFICIAL_RECORD_API,
    verification: "RUNTIME_CAPABILITY_UNVERIFIED",
  });
}

function sync(payload) {
  // Do not substitute guessed book.Tables/DataTables/EnsureFields/DeleteWhere
  // helpers. Application.Sheet/Field/Record signatures must be verified in
  // the deployed WPS runtime before this branch can perform writes.
  return response({
    success: false,
    error_code: "WPS_SMART_SHEET_RUNTIME_UNVERIFIED",
    message: "智能表格 AirScript 多维表写入接口尚未完成运行时验收",
    parent_batch_id: payload.parent_batch_id,
    target_batch_id: payload.target_batch_id,
    site_id: payload.site_id,
    business_key: payload.business_key,
    snapshot_revision: payload.snapshot_revision,
    snapshot_sha256: payload.snapshot_sha256,
    official_api_surface: OFFICIAL_RECORD_API,
  });
}

function main() {
  const args = argv();
  if (args.operation === "connection_test") return connectionTest();
  if (args.operation === "sync_trackside_ap_business") return sync(args);
  return response({ success: false, error_code: "OPERATION_UNSUPPORTED", message: "unsupported operation" });
}

// Explicit execution entry point. Confirm the returned JSON in the WPS editor
// before using the newly copied webhook in production.
main();
