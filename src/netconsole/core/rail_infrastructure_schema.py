"""Canonical, additive site schema for rail engineering relationships."""

RAIL_INFRASTRUCTURE_SCHEMA = """
CREATE TABLE IF NOT EXISTS rail_infra_node (
    node_uid TEXT PRIMARY KEY NOT NULL CHECK (length(trim(node_uid)) > 0),
    node_type TEXT NOT NULL CHECK (node_type IN ('station', 'depot', 'parking_yard', 'cocc', 'bocc')),
    code TEXT NOT NULL DEFAULT '',
    official_name TEXT NOT NULL CHECK (length(trim(official_name)) > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_rail_infra_station_code
    ON rail_infra_node(code) WHERE node_type = 'station' AND code <> '';
CREATE TABLE IF NOT EXISTS rail_infra_node_name (
    name_id TEXT PRIMARY KEY NOT NULL,
    node_uid TEXT NOT NULL REFERENCES rail_infra_node(node_uid) ON DELETE RESTRICT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    name_type TEXT NOT NULL CHECK (name_type IN ('engineering', 'historical')),
    source TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from)
);
CREATE INDEX IF NOT EXISTS ix_rail_infra_node_name ON rail_infra_node_name(node_uid);
CREATE TABLE IF NOT EXISTS rail_infra_project (
    project_id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    stage TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rail_infra_node_project (
    node_uid TEXT NOT NULL REFERENCES rail_infra_node(node_uid) ON DELETE RESTRICT,
    project_id TEXT NOT NULL REFERENCES rail_infra_project(project_id) ON DELETE RESTRICT,
    PRIMARY KEY (node_uid, project_id)
);
CREATE TABLE IF NOT EXISTS rail_infra_device_project (
    device_uuid TEXT NOT NULL REFERENCES devices(device_uuid) ON DELETE RESTRICT,
    project_id TEXT NOT NULL REFERENCES rail_infra_project(project_id) ON DELETE RESTRICT,
    commissioning_stage TEXT NOT NULL DEFAULT '',
    engineering_status TEXT NOT NULL DEFAULT '',
    collect_enabled INTEGER CHECK (collect_enabled IN (0, 1)),
    statistics_enabled INTEGER CHECK (statistics_enabled IN (0, 1)),
    PRIMARY KEY (device_uuid, project_id)
);
CREATE TABLE IF NOT EXISTS rail_infra_device_link (
    node_uid TEXT NOT NULL REFERENCES rail_infra_node(node_uid) ON DELETE RESTRICT,
    device_uuid TEXT NOT NULL REFERENCES devices(device_uuid) ON DELETE RESTRICT,
    engineering_role TEXT NOT NULL DEFAULT '',
    section_uid TEXT,
    PRIMARY KEY (node_uid, device_uuid)
);
CREATE TABLE IF NOT EXISTS rail_infra_device_section (
    device_uuid TEXT NOT NULL REFERENCES devices(device_uuid) ON DELETE RESTRICT,
    section_uid TEXT NOT NULL,
    engineering_role TEXT NOT NULL DEFAULT '',
    installation_location TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (device_uuid, section_uid)
);
CREATE INDEX IF NOT EXISTS ix_rail_infra_device_section_section
    ON rail_infra_device_section(section_uid);
CREATE TABLE IF NOT EXISTS rail_infra_ac_service (
    ac_device_uuid TEXT NOT NULL REFERENCES devices(device_uuid) ON DELETE RESTRICT,
    node_uid TEXT NOT NULL REFERENCES rail_infra_node(node_uid) ON DELETE RESTRICT,
    PRIMARY KEY (ac_device_uuid, node_uid)
);
CREATE TABLE IF NOT EXISTS rail_infra_train (
    train_uid TEXT PRIMARY KEY NOT NULL,
    train_no TEXT NOT NULL UNIQUE CHECK (length(trim(train_no)) > 0),
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rail_infra_train_mr (
    assignment_id TEXT PRIMARY KEY NOT NULL,
    train_uid TEXT NOT NULL REFERENCES rail_infra_train(train_uid) ON DELETE RESTRICT,
    device_uuid TEXT NOT NULL REFERENCES devices(device_uuid) ON DELETE RESTRICT,
    position TEXT NOT NULL CHECK (position IN ('CT', 'CW')),
    active_from TEXT NOT NULL,
    active_to TEXT,
    CHECK (active_to IS NULL OR active_to > active_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_rail_infra_active_train_position
    ON rail_infra_train_mr(train_uid, position) WHERE active_to IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rail_infra_active_mr
    ON rail_infra_train_mr(device_uuid) WHERE active_to IS NULL;
CREATE TABLE IF NOT EXISTS rail_infra_relation_history (
    event_id TEXT PRIMARY KEY NOT NULL,
    relation_type TEXT NOT NULL,
    relation_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('create', 'update', 'terminate', 'replace')),
    source_uid TEXT NOT NULL DEFAULT '',
    target_uid TEXT NOT NULL DEFAULT '',
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    effective_from TEXT,
    effective_to TEXT,
    reason TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT '',
    changed_at TEXT NOT NULL,
    revision TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_rail_infra_relation_history_lookup
    ON rail_infra_relation_history(relation_type, relation_id, changed_at DESC);
CREATE TABLE IF NOT EXISTS rail_infra_relation_audit (
    audit_id TEXT PRIMARY KEY NOT NULL,
    event_id TEXT NOT NULL REFERENCES rail_infra_relation_history(event_id) ON DELETE RESTRICT,
    site_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_infra_node_project_insert
AFTER INSERT ON rail_infra_node_project BEGIN
    UPDATE schema_metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_infra_node_project_delete
AFTER DELETE ON rail_infra_node_project BEGIN
    UPDATE schema_metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_infra_device_link_insert
AFTER INSERT ON rail_infra_device_link BEGIN
    UPDATE schema_metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_infra_device_link_update
AFTER UPDATE ON rail_infra_device_link BEGIN
    UPDATE schema_metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_infra_device_link_delete
AFTER DELETE ON rail_infra_device_link BEGIN
    UPDATE schema_metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_infra_device_section_insert
AFTER INSERT ON rail_infra_device_section BEGIN
    UPDATE schema_metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_infra_device_section_update
AFTER UPDATE ON rail_infra_device_section BEGIN
    UPDATE schema_metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_infra_device_section_delete
AFTER DELETE ON rail_infra_device_section BEGIN
    UPDATE schema_metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_infra_ac_service_insert
AFTER INSERT ON rail_infra_ac_service BEGIN
    UPDATE schema_metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_infra_ac_service_delete
AFTER DELETE ON rail_infra_ac_service BEGIN
    UPDATE schema_metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_infra_train_mr_insert
AFTER INSERT ON rail_infra_train_mr BEGIN
    UPDATE schema_metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_infra_train_mr_update
AFTER UPDATE ON rail_infra_train_mr BEGIN
    UPDATE schema_metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE key = 'base_data_revision';
END;
CREATE TRIGGER IF NOT EXISTS trg_base_revision_rail_infra_relation_history_insert
AFTER INSERT ON rail_infra_relation_history BEGIN
    UPDATE schema_metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE key = 'base_data_revision';
END;
"""

RAIL_INFRASTRUCTURE_TABLES = frozenset(
    (
        "rail_infra_node",
        "rail_infra_node_name",
        "rail_infra_project",
        "rail_infra_node_project",
        "rail_infra_device_project",
        "rail_infra_device_link",
        "rail_infra_device_section",
        "rail_infra_ac_service",
        "rail_infra_train",
        "rail_infra_train_mr",
        "rail_infra_relation_history",
        "rail_infra_relation_audit",
    )
)
