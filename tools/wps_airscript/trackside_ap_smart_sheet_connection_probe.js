// NetConsole read-only WPS_SMART_SHEET connection probe.
const PROTOCOL_VERSION = 2;
const SCRIPT_VERSION = "2.2.0-smart";
const DEPLOYMENT_ID = "trackside-ap-smart-2.2.0";
const DOCUMENT_ID = "cbRdGQdb10R9";
const TARGET_TYPE = "WPS_SMART_SHEET";
const TARGET_CODE = "wps_smart_sheet";
const RUNTIME_CAPABILITY = "RUNTIME_UNVERIFIED";

function listValue(value, names) {
  if (Array.isArray(value)) return value;
  for (const name of names) {
    if (value && Array.isArray(value[name])) return value[name];
  }
  return [];
}

function sheetName(sheet) {
  return String((sheet && (sheet.Name || sheet.name)) || "");
}

function recordFields(record) {
  return (record && (record.fields || record.Fields)) || {};
}

function readMetadata() {
  if (!Application.Sheet || typeof Application.Sheet.GetSheets !== "function") {
    throw new Error("Application.Sheet.GetSheets unavailable");
  }
  const sheet = listValue(Application.Sheet.GetSheets(), ["sheets", "Sheets"])
    .find((item) => sheetName(item) === "_NetConsoleSyncMeta");
  if (!sheet) return {};
  if (!sheet.Record || typeof sheet.Record.GetRecords !== "function") {
    throw new Error("_NetConsoleSyncMeta Record.GetRecords unavailable");
  }
  const values = {};
  let offset = null;
  let first = true;
  do {
    const page = sheet.Record.GetRecords({ PageSize: 100, Offset: offset });
    for (const record of listValue(page, ["records", "Records"])) {
      const fields = recordFields(record);
      const key = String(fields.Key || fields.key || "");
      if (key) values[key] = String(fields.Value || fields.value || "");
    }
    offset = (page && (page.offset || page.Offset)) || null;
    first = false;
  } while (first || offset);
  return values;
}

function bindingDiagnostics(args, values) {
  const remoteBindingId = String(values.binding_id || "");
  const remoteDocumentId = String(values.document_id || "");
  const remoteSiteId = String(values.site_id || "");
  const remoteBusinessKey = String(values.business_key || "");
  const remoteTargetCode = String(values.target_code || "");
  const remoteTargetType = String(values.target_type || "");
  const identity = {
    document_identity_match: Boolean(remoteDocumentId) && remoteDocumentId === DOCUMENT_ID,
    site_identity_match: Boolean(remoteSiteId) && remoteSiteId === String(args.site_id || ""),
    business_identity_match: Boolean(remoteBusinessKey) && remoteBusinessKey === String(args.business_key || ""),
    target_code_match: Boolean(remoteTargetCode) && remoteTargetCode === TARGET_CODE,
    target_type_match: Boolean(remoteTargetType) && remoteTargetType === TARGET_TYPE,
  };
  const allMatch = Object.values(identity).every(Boolean);
  return {
    binding_status: remoteBindingId ? (allMatch && remoteBindingId === String(args.binding_id || "") ? "BOUND" : "MISMATCH") : "UNBOUND",
    local_binding_id: String(args.binding_id || ""),
    remote_binding_id: remoteBindingId,
    binding_id_match: Boolean(remoteBindingId) && remoteBindingId === String(args.binding_id || ""),
    remote_document_id: remoteDocumentId,
    remote_site_id: remoteSiteId,
    remote_business_key: remoteBusinessKey,
    remote_target_code: remoteTargetCode,
    remote_target_type: remoteTargetType,
    ...identity,
  };
}

function readBindingDiagnostics(args, warnings) {
  try {
    return bindingDiagnostics(args, readMetadata());
  } catch (error) {
    warnings.push({
      capability: "binding_readback",
      message: String((error && error.message) || error).slice(0, 500),
    });
    return {
      ...bindingDiagnostics(args, {}),
      binding_status: "UNKNOWN",
    };
  }
}

function main() {
  const context = (typeof Context !== "undefined" && Context.argv) || {};
  const args = context.Context && context.Context.argv ? context.Context.argv : context;
  const warnings = [];
  const binding = readBindingDiagnostics(args, warnings);
  return JSON.stringify({
    success: true,
    protocol_version: PROTOCOL_VERSION,
    script_version: SCRIPT_VERSION,
    deployment_id: DEPLOYMENT_ID,
    document_id: DOCUMENT_ID,
    target_type: TARGET_TYPE,
    target_code: TARGET_CODE,
    script_id: String(args.script_id || args.expected_script_id || ""),
    runtime_capability: RUNTIME_CAPABILITY,
    operation: String(args.operation || "connection_test"),
    ...binding,
    warnings,
    objects: [],
    verification: "CONNECTION_PROBE_ONLY",
  });
}

return main();
