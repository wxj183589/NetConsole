// NetConsole read-only WPS_STANDARD_SPREADSHEET connection probe.
const PROTOCOL_VERSION = 2;
const SCRIPT_VERSION = "2.8.4-standard";
const DEPLOYMENT_ID = "trackside-ap-standard-2.8.4";
const DOCUMENT_ID = "549847228994";
const TARGET_TYPE = "WPS_STANDARD_SPREADSHEET";
const TARGET_CODE = "wps_standard_spreadsheet";
const RUNTIME_CAPABILITY = "DEPLOYMENT_PENDING";

function isLegacyBindingId(value) {
  return /^wst_[0-9a-f]{32}$/i.test(String(value || ""));
}

function requestedBindingId(args) {
  return String(args.new_binding_id || args.binding_id || "");
}

function bindingDiagnostics(args, meta) {
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

function main() {
  const context = (typeof Context !== "undefined" && Context.argv) || {};
  const args = context.Context && context.Context.argv ? context.Context.argv : context;
  const sheets = Application.Worksheets;
  let meta = null;
  for (let index = 0; index < sheets.Count; index += 1) {
    const sheet = sheets.Item(index + 1);
    if (String(sheet.Name || "") !== "_NetConsoleSyncMeta") continue;
    const values = sheet.Range("A1:B20").Value2;
    meta = {};
    for (const row of values || []) if (row && row[0]) meta[String(row[0])] = row[1];
    break;
  }
  const operation = String(args.operation || "connection_test");
  if (operation === "migrate_legacy_binding") {
    return JSON.stringify({
      success: false,
      error_code: "WPS_BINDING_MIGRATION_REQUIRES_SYNC_SCRIPT",
      message: "只读连接探针不能迁移旧版绑定标识，请先部署正式同步脚本",
      protocol_version: PROTOCOL_VERSION,
      script_version: SCRIPT_VERSION,
      deployment_id: DEPLOYMENT_ID,
      document_id: DOCUMENT_ID,
      target_type: TARGET_TYPE,
      target_code: TARGET_CODE,
      script_id: String(args.script_id || args.expected_script_id || ""),
      runtime_capability: RUNTIME_CAPABILITY,
      operation: operation,
      ...bindingDiagnostics(args, meta),
    });
  }
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
    operation: operation,
    ...bindingDiagnostics(args, meta),
    objects: [],
    verification: "CONNECTION_PROBE_ONLY",
  });
}

return main();
