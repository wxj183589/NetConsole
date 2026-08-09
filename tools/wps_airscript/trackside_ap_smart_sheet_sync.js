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
const PROBE_RECORD_BATCH_SIZE = 20;
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

function connectionTest(args) {
  const warnings = [];
  try {
    const binding = safeBindingDiagnostics(args, warnings);
    return response({
      success: true,
      objects: [],
      official_api_surface: OFFICIAL_RECORD_API,
      verification: "CONNECTION_AND_BINDING_READBACK",
      ...binding,
      warnings,
    });
  } catch (error) {
    return response({ success: false, error_code: "WPS_SMART_BINDING_READ_FAILED", message: String((error && error.message) || error).slice(0, 500) });
  }
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
  let probeRecordIds = [];

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
      const requested = Array.from({ length: PROBE_RECORD_BATCH_SIZE }, (_value, index) => ({
        fields: { "探针文本": String(args.probe_id || "probe"), "探针数字": index + 1 },
      }));
      const created = probeSheet.Record.CreateRecords({
        Records: requested,
      });
      const records = recordsFrom(created);
      probeRecordIds = records.map(recordId).filter(Boolean);
      if (probeRecordIds.length !== PROBE_RECORD_BATCH_SIZE) throw new Error("Record.CreateRecords 批量创建未返回完整记录 ID");
      return created;
    });
    capability(core, failures, "record_read", () => {
      const records = readAllRecords(probeSheet, 100);
      const found = records.find((record) => recordId(record) === probeRecordIds[0]);
      if (!found || Number(recordFields(found)["探针数字"]) !== 1) throw new Error("Record.GetRecords 写后读回不一致");
      if (!probeRecordIds.every((id) => records.some((record) => recordId(record) === id))) throw new Error("Record.GetRecords 批量读回数量不一致");
      return records;
    });
    capability(core, failures, "record_update", () => {
      probeSheet.Record.UpdateRecords({ Records: [{ id: probeRecordIds[0], fields: { "探针数字": 200 } }] });
      const found = readAllRecords(probeSheet, 100).find((record) => recordId(record) === probeRecordIds[0]);
      if (!found || Number(recordFields(found)["探针数字"]) !== 200) throw new Error("Record.UpdateRecords 更新后读回不一致");
      return found;
    });
    capability(core, failures, "record_delete", () => {
      probeSheet.Record.DeleteRecords({ RecordIds: probeRecordIds });
      if (readAllRecords(probeSheet, 100).some((record) => probeRecordIds.includes(recordId(record)))) {
        throw new Error("Record.DeleteRecords 删除后仍可读到记录");
      }
      probeRecordIds = [];
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

  if (probeSheet && probeRecordIds.length) {
    try { probeSheet.Record.DeleteRecords({ RecordIds: probeRecordIds }); } catch (error) {
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
    verified_record_batch_size: coreVerified ? PROBE_RECORD_BATCH_SIZE : 0,
    probe_id: String(args.probe_id || ""),
    ...safeBindingDiagnostics(args, warnings),
  });
}

const META_SHEET = "_NetConsoleSyncMeta";
const DEFAULT_RECORD_BATCH_SIZE = 20;

function fieldName(field) {
  return String((field && (field.name || field.Name)) || "");
}

function fieldType(field) {
  return String((field && (field.type || field.Type)) || "");
}

function ensureFields(sheet, requestedFields) {
  const existing = listValue(sheet.Field.GetFields(), ["fields", "Fields"]);
  const byName = {};
  existing.forEach((field) => { byName[fieldName(field)] = field; });
  const missing = [];
  requestedFields.forEach((field) => {
    const current = byName[field.name];
    if (current && fieldType(current) && fieldType(current) !== field.type) {
      throw Object.assign(new Error(`字段类型冲突：${field.name} ${fieldType(current)} != ${field.type}`), { code: "WPS_SMART_FIELD_TYPE_MISMATCH" });
    }
    if (!current) missing.push({ name: field.name, type: field.type });
  });
  if (missing.length) sheet.Field.CreateFields({ Fields: missing });
  const readback = listValue(sheet.Field.GetFields(), ["fields", "Fields"]);
  requestedFields.forEach((field) => {
    const current = readback.find((item) => fieldName(item) === field.name);
    if (!current || (fieldType(current) && fieldType(current) !== field.type)) {
      throw new Error(`字段 Schema 读回不一致：${field.name}`);
    }
  });
  return readback;
}

function ensureBusinessSheet(sheetDto) {
  let sheet = findSheet(sheetDto.sheet_name);
  if (!sheet) {
    if (!Application.Sheet || typeof Application.Sheet.CreateSheet !== "function") {
      throw new Error("Application.Sheet.CreateSheet unavailable");
    }
    Application.Sheet.CreateSheet({
      Name: sheetDto.sheet_name,
      Fields: sheetDto.fields.map((field) => ({ name: field.name, type: field.type })),
      Views: [{ name: "表格", type: "Grid" }],
    });
    sheet = findSheet(sheetDto.sheet_name);
  }
  if (!sheet || !sheetId(sheet)) throw new Error(`数据表创建后无法读回：${sheetDto.sheet_name}`);
  ensureFields(sheet, sheetDto.fields);
  return sheet;
}

function deleteRecordsBatched(sheet, ids, batchSize) {
  for (let index = 0; index < ids.length; index += batchSize) {
    const part = ids.slice(index, index + batchSize);
    if (part.length) sheet.Record.DeleteRecords({ RecordIds: part });
  }
}

function createRecordsBatched(sheet, records, batchSize) {
  const created = [];
  for (let index = 0; index < records.length; index += batchSize) {
    const part = records.slice(index, index + batchSize);
    if (!part.length) continue;
    created.push(...recordsFrom(sheet.Record.CreateRecords({ Records: part })));
  }
  return created;
}

function updateRecordsBatched(sheet, records, batchSize) {
  for (let index = 0; index < records.length; index += batchSize) {
    const part = records.slice(index, index + batchSize);
    if (part.length) sheet.Record.UpdateRecords({ Records: part });
  }
}

function metadataValues() {
  const sheet = findSheet(META_SHEET);
  if (!sheet) return { sheet: null, records: [], values: {} };
  const records = readAllRecords(sheet, 100);
  const values = {};
  records.forEach((record) => {
    const fields = recordFields(record);
    const key = String(fields.Key || fields.key || "");
    if (key) values[key] = String(fields.Value || fields.value || "");
  });
  return { sheet, records, values };
}

function ensureMetaSheet() {
  let sheet = findSheet(META_SHEET);
  if (!sheet) {
    Application.Sheet.CreateSheet({
      Name: META_SHEET,
      Fields: [
        { name: "Key", type: "MultiLineText" },
        { name: "Value", type: "MultiLineText" },
      ],
      Views: [{ name: "表格", type: "Grid" }],
    });
    sheet = findSheet(META_SHEET);
  }
  if (!sheet || !sheetId(sheet)) throw new Error("_NetConsoleSyncMeta 创建后无法读回");
  ensureFields(sheet, [
    { name: "Key", type: "MultiLineText" },
    { name: "Value", type: "MultiLineText" },
  ]);
  return sheet;
}

function writeMetadata(entries) {
  const current = metadataValues();
  const sheet = current.sheet || ensureMetaSheet();
  const records = current.records;
  const updates = [];
  const creates = [];
  Object.keys(entries).forEach((key) => {
    const record = records.find((item) => {
      const fields = recordFields(item);
      return String(fields.Key || fields.key || "") === key;
    });
    if (record && recordId(record)) {
      updates.push({ id: recordId(record), fields: { Value: String(entries[key]) } });
    } else {
      creates.push({ fields: { Key: key, Value: String(entries[key]) } });
    }
  });
  if (updates.length) updateRecordsBatched(sheet, updates, DEFAULT_RECORD_BATCH_SIZE);
  if (creates.length) createRecordsBatched(sheet, creates, DEFAULT_RECORD_BATCH_SIZE);
  return sheet;
}

function bindingDiagnostics(payload, metadata) {
  const values = metadata.values || {};
  const remoteBindingId = String(values.binding_id || "");
  const remoteDocumentId = String(values.document_id || "");
  const remoteSiteId = String(values.site_id || "");
  const remoteBusinessKey = String(values.business_key || "");
  const remoteTargetCode = String(values.target_code || "");
  const remoteTargetType = String(values.target_type || "");
  const identity = {
    document_match: remoteDocumentId === DOCUMENT_ID,
    site_match: remoteSiteId === String(payload.site_id || ""),
    business_match: remoteBusinessKey === String(payload.business_key || ""),
    target_code_match: remoteTargetCode === TARGET_CODE,
    target_type_match: remoteTargetType === TARGET_TYPE,
  };
  const allMatch = Object.values(identity).every(Boolean);
  return {
    binding_status: remoteBindingId ? (allMatch && remoteBindingId === String(payload.binding_id || "") ? "BOUND" : "MISMATCH") : "UNBOUND",
    local_binding_id: String(payload.binding_id || ""),
    remote_binding_id: remoteBindingId,
    binding_id_match: Boolean(remoteBindingId) && remoteBindingId === String(payload.binding_id || ""),
    remote_document_id: remoteDocumentId,
    remote_site_id: remoteSiteId,
    remote_business_key: remoteBusinessKey,
    remote_target_code: remoteTargetCode,
    remote_target_type: remoteTargetType,
    document_identity_match: identity.document_match,
    site_identity_match: identity.site_match,
    business_identity_match: identity.business_match,
    target_code_match: identity.target_code_match,
    target_type_match: identity.target_type_match,
  };
}

function unknownBindingDiagnostics(payload) {
  return {
    binding_status: "UNKNOWN",
    local_binding_id: String(payload.binding_id || ""),
    remote_binding_id: "",
    binding_id_match: false,
    remote_document_id: "",
    remote_site_id: "",
    remote_business_key: "",
    remote_target_code: "",
    remote_target_type: "",
    document_identity_match: false,
    site_identity_match: false,
    business_identity_match: false,
    target_code_match: false,
    target_type_match: false,
  };
}

function safeBindingDiagnostics(payload, warnings) {
  try {
    return bindingDiagnostics(payload, metadataValues());
  } catch (error) {
    warnings.push({
      capability: "binding_readback",
      message: String((error && error.message) || error).slice(0, 500),
    });
    return unknownBindingDiagnostics(payload);
  }
}

function verifyBinding(payload, metadata) {
  const diagnosed = bindingDiagnostics(payload, metadata);
  if (diagnosed.binding_status === "MISMATCH") {
    const error = new Error("智能表格绑定身份不一致");
    error.code = "WPS_DOCUMENT_BINDING_MISMATCH";
    error.details = diagnosed;
    throw error;
  }
  if (diagnosed.binding_status === "UNBOUND" && payload.initialize_binding !== true) {
    const error = new Error("智能表格尚未绑定当前局点，需要显式确认初始化");
    error.code = "WPS_DOCUMENT_UNBOUND";
    error.details = diagnosed;
    throw error;
  }
  if (diagnosed.binding_status === "UNBOUND") {
    writeMetadata({
      document_id: DOCUMENT_ID,
      binding_id: String(payload.binding_id || ""),
      site_id: String(payload.site_id || ""),
      business_key: String(payload.business_key || ""),
      target_code: TARGET_CODE,
      target_type: TARGET_TYPE,
    });
    return bindingDiagnostics(payload, metadataValues());
  }
  return diagnosed;
}

function recordsByBatch(records, batchId) {
  return records.filter((record) => String(recordFields(record)._NC_BATCH_ID || "") === batchId);
}

function verifyRecordBatch(records, expected, batchId) {
  const actual = recordsByBatch(records, batchId);
  const expectedKeys = expected.map((record) => String(record.fields._NC_ROW_KEY || ""));
  const actualKeys = actual.map((record) => String(recordFields(record)._NC_ROW_KEY || ""));
  return actual.length === expected.length && expectedKeys.every((key) => actualKeys.includes(key));
}

function syncSmartSheet(sheetDto, batchSize, batchId) {
  const sheet = ensureBusinessSheet(sheetDto);
  const expectedRecords = sheetDto.records.map((record) => ({ fields: record.fields }));
  let remoteRecords = readAllRecords(sheet, 100);
  let createdCount = 0;
  const existingBatch = recordsByBatch(remoteRecords, batchId);
  if (sheetDto.sync_mode === "APPEND_SNAPSHOT") {
    if (existingBatch.length && !verifyRecordBatch(remoteRecords, expectedRecords, batchId)) {
      deleteRecordsBatched(sheet, existingBatch.map(recordId).filter(Boolean), batchSize);
      remoteRecords = readAllRecords(sheet, 100);
    }
    if (!verifyRecordBatch(remoteRecords, expectedRecords, batchId)) {
      createRecordsBatched(sheet, expectedRecords, batchSize);
      createdCount = expectedRecords.length;
      remoteRecords = readAllRecords(sheet, 100);
    }
    if (!verifyRecordBatch(remoteRecords, expectedRecords, batchId)) throw new Error(`历史批次读回数量不一致：${sheetDto.sheet_name}`);
    return { sheet_name: sheetDto.sheet_name, mode: "APPEND_SNAPSHOT", field_count: sheetDto.fields.length, records_created: createdCount, records_deleted: 0, records_read_back: recordsByBatch(remoteRecords, batchId).length };
  }
  if (existingBatch.length && !verifyRecordBatch(remoteRecords, expectedRecords, batchId)) {
    deleteRecordsBatched(sheet, existingBatch.map(recordId).filter(Boolean), batchSize);
    remoteRecords = readAllRecords(sheet, 100);
  }
  if (!verifyRecordBatch(remoteRecords, expectedRecords, batchId)) {
    createRecordsBatched(sheet, expectedRecords, batchSize);
    createdCount = expectedRecords.length;
    remoteRecords = readAllRecords(sheet, 100);
  }
  if (!verifyRecordBatch(remoteRecords, expectedRecords, batchId)) throw new Error(`全量替换新记录读回不一致：${sheetDto.sheet_name}`);
  const oldIds = remoteRecords
    .filter((record) => String(recordFields(record)._NC_BATCH_ID || "") !== batchId)
    .map(recordId)
    .filter(Boolean);
  deleteRecordsBatched(sheet, oldIds, batchSize);
  const finalRecords = readAllRecords(sheet, 100);
  if (!verifyRecordBatch(finalRecords, expectedRecords, batchId) || finalRecords.length !== expectedRecords.length) {
    throw new Error(`全量替换删除旧记录后读回不一致：${sheetDto.sheet_name}`);
  }
  return { sheet_name: sheetDto.sheet_name, mode: "FULL_REPLACE", field_count: sheetDto.fields.length, records_created: createdCount, records_deleted: oldIds.length, records_read_back: finalRecords.length };
}

function reorderSmartSheets(sheetDtos) {
  const expected = sheetDtos.slice().sort((left, right) => left.sheet_order - right.sheet_order).map((sheet) => sheet.sheet_name);
  for (let index = 1; index < expected.length; index += 1) {
    const previous = findSheet(expected[index - 1]);
    const current = findSheet(expected[index]);
    if (!previous || !current) throw new Error(`业务 Sheet 缺失：${expected[index]}`);
    current.Move({ Before: null, After: sheetId(previous) });
  }
  const actual = sheets().filter((sheet) => expected.includes(sheetName(sheet))).map(sheetName);
  return { expected, actual, verified: expected.join("\u0001") === actual.join("\u0001") };
}

function sheetOrderProbe(args) {
  const firstName = "_NetConsoleSmartProbeA";
  const secondName = "_NetConsoleSmartProbeB";
  let first = findSheet(firstName);
  let second = findSheet(secondName);
  const warnings = [];
  try {
    if (!first) {
      Application.Sheet.CreateSheet({ Name: firstName, Fields: [{ name: "值", type: "MultiLineText" }], Views: [{ name: "表格", type: "Grid" }] });
      first = findSheet(firstName);
    }
    if (!second) {
      Application.Sheet.CreateSheet({ Name: secondName, Fields: [{ name: "值", type: "MultiLineText" }], Views: [{ name: "表格", type: "Grid" }] });
      second = findSheet(secondName);
    }
    if (!first || !second) throw new Error("智能表格排序探针 Sheet 创建后无法读回");
    second.Move({ Before: sheetId(first), After: null });
    const before = sheets().filter((sheet) => [firstName, secondName].includes(sheetName(sheet))).map(sheetName);
    const beforeVerified = before.join("\u0001") === `${secondName}\u0001${firstName}`;
    second.Move({ Before: null, After: sheetId(first) });
    const after = sheets().filter((sheet) => [firstName, secondName].includes(sheetName(sheet))).map(sheetName);
    const afterVerified = after.join("\u0001") === `${firstName}\u0001${secondName}`;
    return response({ success: beforeVerified && afterVerified, status: beforeVerified && afterVerified ? "SUCCESS" : "FAILED", error_code: beforeVerified && afterVerified ? "" : "WPS_SMART_SHEET_ORDER_VERIFY_FAILED", message: beforeVerified && afterVerified ? "智能表格 Sheet.Move 排序探针通过" : "智能表格 Sheet.Move 排序读回不一致", sheet_order_verified: beforeVerified && afterVerified, sheet_move_before_verified: beforeVerified, sheet_move_after_verified: afterVerified, expected_sheet_order: [firstName, secondName], actual_sheet_order: after, warnings, probe_id: String(args.probe_id || "") });
  } catch (error) {
    warnings.push({ capability: "sheet_move", message: String((error && error.message) || error).slice(0, 500) });
    return response({ success: false, status: "FAILED", error_code: "WPS_SMART_SHEET_ORDER_PROBE_FAILED", message: "智能表格 Sheet.Move 排序探针失败", warnings, probe_id: String(args.probe_id || "") });
  }
}

function sync(payload) {
  try {
    if (String(payload.runtime_capability || "") !== "VERIFIED" && payload.runtime_probe_verified !== true) {
      throw Object.assign(new Error("智能表格运行时核心能力尚未验证"), { code: "WPS_SMART_SHEET_RUNTIME_UNVERIFIED" });
    }
    const metadata = metadataValues();
    const binding = verifyBinding(payload, metadata);
    const workbook = payload.smart_workbook;
    if (!workbook || !Array.isArray(workbook.sheets) || workbook.sheets.length !== 9) {
      throw Object.assign(new Error("智能表格 payload 必须包含 9 个业务 Sheet"), { code: "WPS_SMART_WORKBOOK_INVALID" });
    }
    const batchSize = Math.max(1, Math.min(Number(payload.record_batch_size || DEFAULT_RECORD_BATCH_SIZE), DEFAULT_RECORD_BATCH_SIZE));
    const batchId = String(payload.target_batch_id || "");
    const sheetResults = workbook.sheets.slice().sort((left, right) => left.sheet_order - right.sheet_order).map((sheetDto) => syncSmartSheet(sheetDto, batchSize, batchId));
    const order = reorderSmartSheets(workbook.sheets);
    if (!order.verified) throw Object.assign(new Error("智能表格业务 Sheet 顺序读回不一致"), { code: "WPS_SMART_SHEET_ORDER_VERIFY_FAILED" });
    writeMetadata({
      last_target_batch_id: String(payload.target_batch_id || ""),
      last_snapshot_revision: String(payload.snapshot_revision || ""),
      last_snapshot_sha256: String(payload.snapshot_sha256 || ""),
    });
    return response({ success: true, status: "SUCCESS", message: "智能表格同步完成", runtime_capability: "VERIFIED", ...binding, parent_batch_id: payload.parent_batch_id, target_batch_id: payload.target_batch_id, site_id: payload.site_id, business_key: payload.business_key, snapshot_revision: payload.snapshot_revision, snapshot_sha256: payload.snapshot_sha256, sheet_count: sheetResults.length, field_count: sheetResults.reduce((sum, item) => sum + Number(item.field_count || 0), 0), records_created: sheetResults.reduce((sum, item) => sum + Number(item.records_created || 0), 0), records_deleted: sheetResults.reduce((sum, item) => sum + Number(item.records_deleted || 0), 0), records_read_back: sheetResults.reduce((sum, item) => sum + Number(item.records_read_back || 0), 0), sheet_results: sheetResults, sheet_order_verified: true, expected_sheet_order: order.expected, actual_sheet_order: order.actual, history_appended: sheetResults[0] ? Number(sheetResults[0].records_created || 0) : 0 });
  } catch (error) {
    return response({ success: false, error_code: String((error && error.code) || "WPS_SMART_SHEET_SYNC_FAILED"), message: String((error && error.message) || error).slice(0, 500), parent_batch_id: payload.parent_batch_id, target_batch_id: payload.target_batch_id, site_id: payload.site_id, business_key: payload.business_key, snapshot_revision: payload.snapshot_revision, snapshot_sha256: payload.snapshot_sha256 });
  }
}

function main() {
  const args = argv();
  if (args.operation === "connection_test") return connectionTest(args);
  if (args.operation === "smart_runtime_write_probe" || args.operation === "runtime_write_probe") return smartRuntimeWriteProbe(args);
  if (args.operation === "sheet_order_probe") return sheetOrderProbe(args);
  if (args.operation === "sync_trackside_ap_business") return sync(args);
  return response({ success: false, error_code: "OPERATION_UNSUPPORTED", message: "unsupported operation" });
}

// Explicit execution entry point. Confirm the returned JSON in the WPS editor
// before using the newly copied webhook in production.
return main();
