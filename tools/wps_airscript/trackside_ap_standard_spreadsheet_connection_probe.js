// NetConsole read-only WPS_STANDARD_SPREADSHEET connection probe.
const PROTOCOL_VERSION = 2;
const SCRIPT_VERSION = "2.1.0-standard";
const DEPLOYMENT_ID = "trackside-ap-standard-2.1.0";
const DOCUMENT_ID = "549847228994";
const TARGET_TYPE = "WPS_STANDARD_SPREADSHEET";
const TARGET_CODE = "wps_standard_spreadsheet";
const RUNTIME_CAPABILITY = "DEPLOYMENT_PENDING";

function main() {
  const args = (typeof Context !== "undefined" && Context.argv) || {};
  return JSON.stringify({
    success: true,
    protocol_version: PROTOCOL_VERSION,
    script_version: SCRIPT_VERSION,
    deployment_id: DEPLOYMENT_ID,
    document_id: DOCUMENT_ID,
    target_type: TARGET_TYPE,
    target_code: TARGET_CODE,
    runtime_capability: RUNTIME_CAPABILITY,
    operation: String(args.operation || "connection_test"),
    objects: [],
    verification: "CONNECTION_PROBE_ONLY",
  });
}

return main();
