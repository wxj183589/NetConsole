// NetConsole read-only WPS_SMART_SHEET connection probe.
const PROTOCOL_VERSION = 2;
const SCRIPT_VERSION = "2.1.0-smart";
const DEPLOYMENT_ID = "trackside-ap-smart-2.1.0";
const DOCUMENT_ID = "cbRdGQdb10R9";
const TARGET_TYPE = "WPS_SMART_SHEET";
const TARGET_CODE = "wps_smart_sheet";
const RUNTIME_CAPABILITY = "RUNTIME_UNVERIFIED";

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

main();
