# Interface Discovery E3 SSH Connection Path Root Cause

## 1. Scope and safety boundary

This report records Phase 2D-E3-R1 only: root-cause analysis and offline
validation of the failed E3 connection path. It does not authorize or perform
another device attempt.

```text
REAL_DEVICE_CONNECTION_ALLOWED=NO
CONNECTION_ATTEMPTS=0
PRODUCTION_CUTOVER_EXECUTED=NO
WAVE0_EXECUTED=NO
WAVE1_EXECUTED=NO
```

The previous E3 attempt belongs to the earlier authorized validation window.
This R1 run did not reuse that window and did not open a socket. Test targets
use documentation-only addresses and all connection factories are mocked.

## 2. Baseline

```text
BRANCH_BEFORE=codex-A/formal-main-merge
HEAD_BEFORE=50e2f29cd0a17890451448fbd12550525720f5bf
WORKTREE_DIRTY_BEFORE=NO
TARGET=DEVICE-NB10-C7-01
SITE=宁波10号线
VENDOR=H3C
ROLE=switch
COMWARE_MAJOR=7
CAPABILITY=interface.discovery
```

The E3 blocked report records the previous result as an error before the first
comparable cycle. Repository effects were `NONE` and no repository write was
observed.

## 3. Previous E3 failure reconstruction

The previous harness was a temporary local capture runner and is not a tracked
production component. Its bytecode line mapping and the current source were
used only to reconstruct the redacted call site; no credential, host, address,
or raw CLI output is reproduced here.

```text
PREVIOUS_E3_STATUS=FAIL
PREVIOUS_CONNECTION_ATTEMPTS=1
PREVIOUS_FAILURE_STAGE=CONNECTION_FACTORY
PREVIOUS_ERROR_CLASS=RuntimeError
PREVIOUS_ERROR_CODE=PYTHON_DEPENDENCY_MISSING
PREVIOUS_COMMAND_GUARD_REACHED=NO
PREVIOUS_SOCKET_OR_TRANSPORT_REACHED=NO
PREVIOUS_AUTHENTICATION_REACHED=NO
PREVIOUS_COMPARABLE_CYCLES=0
```

Redacted failure summary:

```text
e3_capture_runner.py:240
  connection = ConnectHandler(**build_netmiko_params(prepared))
src/netconsole/services/netmiko_connection.py:129
  from netmiko import ConnectHandler
src/netconsole/services/netmiko_connection.py:131
  RuntimeError("netmiko is not installed")
```

The underlying import failure was that the interpreter used by the temporary
runner did not have the project dependency `netmiko` available. The formal
shared entrypoint translated that import failure into the above RuntimeError.
This happened before Site SSH Relay resolution, before the compatibility
factory, before Paramiko transport creation, before authentication, and before
any device command or Command Guard execution.

The observed runtime evidence was:

```text
E3_INTERPRETER=system Python 3.14.4
E3_NETMIKO_AVAILABLE=NO
CANONICAL_PROJECT_RUNTIME=repository .venv Python 3.13.9
CANONICAL_NETMIKO_AVAILABLE=YES
PACKAGED_RUNTIME_INVOLVED=NO
```

## 4. B2 versus E3 connection path

The audited formal path is:

```text
DeviceRepository / collector
  -> Device.from_mapping + persisted credential resolution
  -> connection_targets(device)
  -> prepared_connection_target(target)
  -> ssh_connection_context(... paths, site_id)
  -> netmiko_connection.ConnectHandler(... build_netmiko_params)
  -> DeviceSSHConnectionFactory / direct compatibility adapter
  -> H3C Netmiko adapter
  -> Command Guard
  -> parser and the existing writer boundary
```

The E3 capture path used the same device target resolution, target preparation,
explicit `PathResolver` and site context, parameter builder, and shared
`netmiko_connection.ConnectHandler` entrypoint. Its intentional difference is
that it captures the read-only comparison result and does not invoke the
production repository writer.

| Layer | B2 successful validation | Previous E3 attempt | R1 conclusion |
|---|---|---|---|
| Device identity | `DEVICE-NB10-C7-01`, H3C SW | Same target identity | Equivalent |
| Site context | Explicit Ningbo 10 line context | Explicit Ningbo 10 line context | Equivalent |
| Credential resolution | Repository/device credential contract | Same resolved target contract | Equivalent |
| Host and port | `connection_targets` and prepared target | Same shared target functions | Equivalent |
| Connection factory | Shared `ConnectHandler` | Same shared entrypoint | Equivalent |
| Adapter | H3C `hp_comware` path | Not reached | No code-path evidence of drift |
| Command Guard | Existing profile guard | Not reached | Offline contract verified |
| Repository writer | Existing Legacy writer in B2 | E3 capture writer disabled | Intentionally isolated |
| Runtime | Project/source runtime | System Python without Netmiko | Root-cause difference |

```text
B2_E3_CONNECTION_PATH_EQUIVALENT=PASS_WITH_VALIDATION_BOUNDARY
DEVICE_RESOLUTION_EQUIVALENT=YES
SITE_CONTEXT_EQUIVALENT=YES
ROLE_NORMALIZATION_EQUIVALENT=YES
VENDOR_NORMALIZATION_EQUIVALENT=YES
CREDENTIAL_RESOLUTION_EQUIVALENT=YES
HOST_RESOLUTION_EQUIVALENT=YES
PORT_RESOLUTION_EQUIVALENT=YES
CONNECTION_FACTORY_EQUIVALENT=YES
SSH_ADAPTER_EQUIVALENT=YES
H3C_ADAPTER_EQUIVALENT=YES
AUTH_METHOD_EQUIVALENT=YES
TIMEOUT_POLICY_EQUIVALENT=YES
COMMAND_GUARD_IN_PATH=YES
COMMAND_GUARD_REACHED_PREVIOUS_E3=NO
REPOSITORY_WRITER_ENABLED_IN_R1=NO
```

`PASS_WITH_VALIDATION_BOUNDARY` means that the connection setup seam is the
same after using the project runtime; it does not claim that a new real-device
session has been completed.

## 5. Relevant code drift audit

The source range after the B2 validation baseline was audited for the shared
SSH path. The relevant changes introduced site relay/routing integration and
controlled interface routing, but the previous E3 attempt failed before any of
those branches could execute:

```text
323bf2e6  interface discovery controlled routing/fallback
25165252  site-level SSH relay integration
bc0d2054  shared SSH exit/compatibility path
ab2f4c64  engineering hardening integration
```

The audit found no second CLI SSH implementation, no direct Paramiko client in
the H3C CLI collector, no new credential loader, and no production parser/DTO/
repository contract change caused by the E3 failure.

```text
PRODUCTION_CONNECTION_PATH_CHANGED=NO
PRODUCTION_CREDENTIAL_RESOLVER_CHANGED=NO
PRODUCTION_H3C_ADAPTER_CHANGED=NO
PACKAGING_PATH_CHANGED=NO
PARSER_CHANGED=NO
DTO_CHANGED=NO
REPOSITORY_SCHEMA_CHANGED=NO
PROFILE_CHANGED=NO
```

## 6. Root cause decision

```text
ROOT_CAUSE_CATEGORY=E3_HARNESS_BUG
ROOT_CAUSE_EVIDENCE_LEVEL=CONFIRMED
ROOT_CAUSE=Temporary E3 runner used a system Python interpreter without the project Netmiko dependency; the shared ConnectHandler converted that import failure to RuntimeError before transport creation.
EXTERNAL_CAUSE_CANNOT_BE_EXCLUDED=NO_FOR_THIS_FAILURE
CODE_PATH_REGRESSION_FOUND=NO
RETRY_BLOCKER=CORRECT_RUNTIME_REQUIRED
```

This is a harness/runtime defect, not evidence of an SSH password failure,
device unreachability, Comware mismatch, relay failure, parser mismatch, or
repository failure. A future authorized window still has to establish one
controlled real connection with the canonical project runtime; R1 does not make
that claim.

## 7. Offline fix and validation

No production connection code was changed. The offline fix is to make the next
controlled runner invocation use the repository's canonical project runtime
with the declared `netmiko` dependency, and to lock the connection seam with
tests. No second SSH implementation, direct Paramiko client, subprocess SSH,
credential loader, or session manager was added.

```text
CODE_CHANGED=NO
TEST_HARNESS_CONTRACT_ADDED=YES
PRODUCTION_CONNECTION_FACTORY_REUSED=YES
PRODUCTION_CREDENTIAL_RESOLVER_REUSED=YES
PRODUCTION_H3C_ADAPTER_REUSED=YES
COMMAND_GUARD_BYPASSED=NO
REPOSITORY_WRITER_ENABLED_IN_VALIDATION=NO
REAL_SOCKET_OPEN_COUNT=0
```

The new offline contract test verifies:

1. B2/formal retry and E3 capture use identical target and Netmiko parameter
   construction.
2. Both paths carry the same explicit site and data-root context.
3. Credential resolution selects the existing local-database SSH fields and
   never requires a parallel credential mechanism.
4. The read-only command subset is accepted and `system-view` is rejected.
5. A socket attempt would fail the test, proving the R1 validation is mock-only.

Existing Shadow, repository, replay, and shared SSH factory tests remain the
writer-isolation and adapter-contract gates. R1 did not invoke a repository
writer and did not modify development or production data.

The R1 validation matrix is:

| Gate | Result |
|---|---|
| New E3 connection-path contract tests | `3 passed` |
| Shared SSH, Command Guard, Shadow, replay, Repository and profile tests | `185 passed` |
| Baseline-aware Python full suite | `4763 passed, 2 skipped, 4 deselected` |
| Python new failures | `0` |
| Docs/path and CI-selection tests | `23 passed` |
| Main contract smoke | `12 passed` |
| Stable architecture green gates | `8/8 PASS` |
| Architecture baseline | `expected=7, actual=7, new=0` |
| Ruff baseline audit | `new=0` (`4` existing findings resolved) |
| Full Ruff | `PASS` |
| Compileall | `PASS` |
| `git diff --check` | `PASS` |
| Real device connection | `NOT EXECUTED` |

The full Python run retained the repository's four exact baseline exclusions;
they are not new R1 failures. The baseline audit reported
`BASELINE_DEBT_MATCH=PASS`.

## 8. Evidence and next gate

```text
REAL_DEVICE_CONNECTION_ALLOWED=NO
CONNECTION_ATTEMPTS=0
RAW_DEVICE_EVIDENCE_CREATED=NO
CREDENTIALS_LOGGED=NO
PRODUCTION_DATA_TOUCHED=NO
DEV_REAL_DATA_TOUCHED=NO
```

The historical E3 local summary remains ignored and local-only. No raw CLI,
database, credential, IP, hostname, MAC, serial number, or token is added to
Git. The next real-device attempt requires a new explicit maintenance window
and must use the canonical project runtime, then stop immediately on any
pre-cycle error.

```text
E3_RETRY_READY=YES
E3_RETRY_READY_MEANING=NEW_AUTHORIZED_CONTROLLED_ATTEMPT_ONLY
NEW_MAINTENANCE_WINDOW_REQUIRED=YES
RC_BASELINE_READY=NO
PHASE2D_E_READY=NO
PHASE2D_READY=NO
```
