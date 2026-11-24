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
"""

RAIL_INFRASTRUCTURE_TABLES = frozenset(
    (
        "rail_infra_node",
        "rail_infra_node_name",
        "rail_infra_project",
        "rail_infra_node_project",
        "rail_infra_device_project",
        "rail_infra_device_link",
        "rail_infra_ac_service",
        "rail_infra_train",
        "rail_infra_train_mr",
    )
)
