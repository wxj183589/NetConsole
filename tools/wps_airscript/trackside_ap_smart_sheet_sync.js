// NetConsole WPS_SMART_SHEET AirScript protocol v2.
// Smart Sheet runtime verification is isolated from all registered business sheets.
const PROTOCOL_VERSION = 2;
const SCRIPT_VERSION = "2.2.0-smart";
const DEPLOYMENT_ID = "trackside-ap-smart-2.2.0";
const DOCUMENT_ID = "cbRdGQdb10R9";
const TARGET_TYPE = "WPS_SMART_SHEET";
const TARGET_CODE = "wps_smart_sheet";
const RUNTIME_CAPABILITY = "RUNTIME_UNVERIFIED";
const PROBE_SHEET = "_NetConsoleSmartProbe";
const OFFICIAL_RECORD_API = [
  "Application.Sheet",
  "sheet.Field",
  "sheet.Record",
  "sheet.Move",
];

function argv() {
  const value = (typeof Context !== "undefined" && Context.argv) || {};
  return value.Context && value.Context.argv ? value.Context.argv : value;
}

function response(value) {
  const contextValue = (typeof Context !== "undefined" && Context.argv) || {};
  const context = contextValue.Context && contextValue.Context.argv ? contextValue.Context.argv : contextValue;
  return JSON.stringify({
    protocol_version: PROTOCOL_VERSION,
    script_version: SCRIPT_VERSION,
    deployment_id: DEPLOYMENT_ID,
    document_id: DOCUMENT_ID,
    target_type: TARGET_TYPE,
    target_code: TARGET_CODE,
    script_id: String(context.script_id || context.expected_script_id || ""),
    runtime_capability: RUNTIME_CAPABILITY,
    ...value,
  });
}

function connectionTest() {
  return response({
    success: true,
    objects: [],
    official_api_surface: OFFICIAL_RECORD_API,
    verification: "CONNECTION_PROBE_ONLY",
  });
}

function listValue(value, names) {
  if (Array.isArray(value)) return value;
  for (const name of names) {
    if (value && Array.isArray(value[name])) return value[name];
  }
  return [];
}

function sheetId(sheet) {
  return String((sheet && (sheet.Id || sheet.id || sheet.SheetId || sheet.sheetId)) || "");
}

function sheetName(sheet) {
  return String((sheet && (sheet.Name || sheet.name)) || "");
}

function sheets() {
  if (!Application.Sheet || typeof Application.Sheet.GetSheets !== "function") {
    throw new Error("Application.Sheet.GetSheets unavailable");
  }
  return listValue(Application.Sheet.GetSheets(), ["sheets", "Sheets"]);
}

function findSheet(name) {
  return sheets().find((sheet) => sheetName(sheet) === name) || null;
}

function recordsFrom(value) {
  return listValue(value, ["records", "Records"]);
}

function recordId(record) {
  return String((record && (record.id || record.Id || record.RecordId)) || "");
}

function recordFields(record) {
  return (record && (record.fields || record.Fields)) || {};
}

function readAllRecords(sheet, pageSize) {
  const result = [];
  let offset = null;
  let first = true;
  do {
    const page = sheet.Record.GetRecords({ PageSize: pageSize, Offset: offset });
    result.push(...recordsFrom(page));
    offset = (page && (page.offset || page.Offset)) || null;
    first = false;
  } while (first || offset);
  return result;
}

function capability(capabilities, failures, key, action) {
  try {
    const value = action();
    capabilities[key] = true;
    return value;
  } catch (error) {
    capabilities[key] = false;
    failures.push({ capability: key, message: String((error && error.message) || error).slice(0, 500) });
    return null;
  }
}

function optionalCapability(capabilities, warnings, key, action) {
  try {
    action();
    capabilities[key] = true;
  } catch (error) {
    capabilities[key] = false;
    warnings.push({ capability: key, message: String((error && error.message) || error).slice(0, 500) });
  }
}

function deleteProbeSheet(sheet, warnings) {
  if (!sheet || typeof sheet.Delete !== "function") {
    warnings.push({ capability: "probe_cleanup", message: "Probe Sheet 删除接口不可用，已保留系统 Probe Sheet" });
    return false;
  }
  try {
    sheet.Delete();
    return !findSheet(PROBE_SHEET);
  } catch (error) {
    warnings.push({ capability: "probe_cleanup", message: String((error && error.message) || error).slice(0, 500) });
    return false;
  }
}

function smartRuntimeWriteProbe(args) {
  const core = {};
  const optional = {};
  const failures = [];
  const warnings = [];
  let probeSheet = null;
  let probeRecordId = "";

  const originalSheets = capability(core, failures, "sheet_enum", () => sheets());
  if (Array.isArray(originalSheets)) {
    const stale = originalSheets.find((sheet) => sheetName(sheet) === PROBE_SHEET);
    if (stale && typeof stale.Delete === "function") {
      try { stale.Delete(); } catch (error) {
        failures.push({ capability: "sheet_create", message: `无法清理旧 Probe Sheet：${String((error && error.message) || error).slice(0, 400)}` });
      }
    }
  }

  probeSheet = capability(core, failures, "sheet_create", () => {
    if (!Application.Sheet || typeof Application.Sheet.CreateSheet !== "function") {
      throw new Error("Application.Sheet.CreateSheet unavailable");
    }
    Application.Sheet.CreateSheet({
      Name: PROBE_SHEET,
      Fields: [{ name: "探针文本", type: "MultiLineText" }],
      Views: [{ name: "表格", type: "Grid" }],
    });
    const created = findSheet(PROBE_SHEET);
    if (!created || !sheetId(created)) throw new Error("Probe Sheet 创建后无法按名称和 ID 读回");
    return created;
  });

  if (probeSheet) {
    capability(core, failures, "field_enum", () => {
      if (!probeSheet.Field || typeof probeSheet.Field.GetFields !== "function") throw new Error("Field.GetFields unavailable");
      return probeSheet.Field.GetFields();
    });
    capability(core, failures, "field_create", () => {
      const created = probeSheet.Field.CreateFields({ Fields: [{ name: "探针数字", type: "Number" }] });
      const values = listValue(created, ["fields", "Fields"]);
      const all = listValue(probeSheet.Field.GetFields(), ["fields", "Fields"]);
      if (![...values, ...all].some((field) => String(field.name || field.Name || "") === "探针数字")) {
        throw new Error("Field.CreateFields 创建后无法读回");
      }
      return created;
    });
    capability(core, failures, "record_create", () => {
      const created = probeSheet.Record.CreateRecords({
        Records: [{ fields: { "探针文本": String(args.probe_id || "probe"), "探针数字": 1 } }],
      });
      const records = recordsFrom(created);
      probeRecordId = recordId(records[0]);
      if (!probeRecordId) throw new Error("Record.CreateRecords 未返回记录 ID");
      return created;
    });
    capability(core, failures, "record_read", () => {
      const records = readAllRecords(probeSheet, 100);
      const found = records.find((record) => recordId(record) === probeRecordId);
      if (!found || Number(recordFields(found)["探针数字"]) !== 1) throw new Error("Record.GetRecords 写后读回不一致");
      return records;
    });
    capability(core, failures, "record_update", () => {
      probeSheet.Record.UpdateRecords({ Records: [{ id: probeRecordId, fields: { "探针数字": 2 } }] });
      const found = readAllRecords(probeSheet, 100).find((record) => recordId(record) === probeRecordId);
      if (!found || Number(recordFields(found)["探针数字"]) !== 2) throw new Error("Record.UpdateRecords 更新后读回不一致");
      return found;
    });
    capability(core, failures, "record_delete", () => {
      probeSheet.Record.DeleteRecords({ RecordIds: [probeRecordId] });
      if (readAllRecords(probeSheet, 100).some((record) => recordId(record) === probeRecordId)) {
        throw new Error("Record.DeleteRecords 删除后仍可读到记录");
      }
      probeRecordId = "";
      return true;
    });
    capability(core, failures, "sheet_move", () => {
      const peers = sheets().filter((sheet) => sheetName(sheet) !== PROBE_SHEET);
      if (!peers.length) throw new Error("缺少用于 Sheet.Move 验证的参照数据表");
      probeSheet.Move({ Before: sheetId(peers[0]), After: null });
      if (sheetName(sheets()[0]) !== PROBE_SHEET) throw new Error("Sheet.Move Before 读回顺序不一致");
      const afterTarget = sheets().filter((sheet) => sheetName(sheet) !== PROBE_SHEET).slice(-1)[0];
      probeSheet.Move({ Before: null, After: sheetId(afterTarget) });
      if (sheetName(sheets().slice(-1)[0]) !== PROBE_SHEET) throw new Error("Sheet.Move After 读回顺序不一致");
      return true;
    });
    optionalCapability(optional, warnings, "view_enum", () => {
      if (!probeSheet.View || typeof probeSheet.View.GetViews !== "function") throw new Error("View.GetViews unavailable");
      probeSheet.View.GetViews();
    });
  } else {
    for (const key of ["field_enum", "field_create", "record_create", "record_read", "record_update", "record_delete", "sheet_move"]) {
      if (!(key in core)) core[key] = false;
    }
  }

  if (probeSheet && probeRecordId) {
    try { probeSheet.Record.DeleteRecords({ RecordIds: [probeRecordId] }); } catch (error) {
      warnings.push({ capability: "probe_record_cleanup", message: String((error && error.message) || error).slice(0, 500) });
    }
  }
  const probeCleanup = deleteProbeSheet(probeSheet, warnings);
  const coreVerified = Object.keys(core).length === 9 && Object.values(core).every(Boolean);
  return response({
    success: coreVerified,
    status: coreVerified ? (warnings.length ? "SUCCESS_WITH_WARNINGS" : "SUCCESS") : "FAILED",
    error_code: coreVerified ? "" : "WPS_SMART_RUNTIME_PROBE_UNVERIFIED",
    message: coreVerified ? "智能表格运行时核心能力探针通过" : "智能表格运行时核心能力探针未通过",
    runtime_capability: coreVerified ? "VERIFIED" : "DEPLOYMENT_PENDING",
    core_verified: coreVerified,
    full_replace_ready: coreVerified,
    append_history_ready: coreVerified,
    core_capabilities: core,
    optional_capabilities: optional,
    capability_failures: failures,
    warnings,
    probe_sheet: PROBE_SHEET,
    probe_cleanup: probeCleanup,
    probe_id: String(args.probe_id || ""),
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
  if (args.operation === "smart_runtime_write_probe" || args.operation === "runtime_write_probe") return smartRuntimeWriteProbe(args);
  if (args.operation === "sync_trackside_ap_business") return sync(args);
  return response({ success: false, error_code: "OPERATION_UNSUPPORTED", message: "unsupported operation" });
}

// Explicit execution entry point. Confirm the returned JSON in the WPS editor
// before using the newly copied webhook in production.
return main();
