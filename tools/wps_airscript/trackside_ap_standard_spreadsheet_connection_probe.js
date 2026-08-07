// NetConsole read-only WPS_STANDARD_SPREADSHEET connection probe.
const PROTOCOL_VERSION = 2;
const SCRIPT_VERSION = "2.3.0-standard";
const DEPLOYMENT_ID = "trackside-ap-standard-2.3.0";
const DOCUMENT_ID = "549847228994";
const TARGET_TYPE = "WPS_STANDARD_SPREADSHEET";
const TARGET_CODE = "wps_standard_spreadsheet";
const RUNTIME_CAPABILITY = "DEPLOYMENT_PENDING";

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
    binding_status: meta && meta.binding_id ? "BOUND" : "UNBOUND",
    ...(meta || {}),
    objects: [],
    verification: "CONNECTION_PROBE_ONLY",
  });
}

return main();
