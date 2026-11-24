"""Engineering-only projection. Runtime/history owners remain independent."""

from datetime import datetime, timezone
from netconsole.models.api.device_detail import DeviceEngineeringContextDTO
from netconsole.repositories.rail_relationship_repository import (
    RailRelationshipRepository,
)


class EngineeringContextQueryService:
    def __init__(self, paths, base_query=None):
        if base_query is None:
            from netconsole.services.rail_transit.base_data_query_service import (
                RailTransitBaseDataQueryService,
            )

            base_query = RailTransitBaseDataQueryService(paths)
        self.paths = paths
        self.base_query = base_query

    @classmethod
    def from_site_database(cls, database, site_id):
        # Standalone snapshot tools may use a noncanonical fixture database.
        # Only the existing canonical Site layout can supply a context root.
        from pathlib import Path
        from netconsole.core.paths import PathResolver

        path = Path(database.path).resolve()
        if (
            path.parent.name != "db"
            or path.parent.parent.name != site_id
            or path.parents[2].name != "sites"
        ):
            return None
        return cls(PathResolver(data_root=path.parents[3]))

    def contexts(self, site_id, device_uuids, *, at_time="", expected_revision=""):
        ids = list(dict.fromkeys(str(v) for v in device_uuids if v))
        stamp = datetime.now(timezone.utc).isoformat()
        defaults = {
            uid: DeviceEngineeringContextDTO(
                device_uuid=uid,
                context_updated_at=stamp,
                temporal_scope="historical" if at_time else "current",
                effective_at=at_time,
                reason_code="ENGINEERING_CONTEXT_UNAVAILABLE",
            )
            for uid in ids
        }
        if not ids:
            return defaults
        try:
            before = self.base_query.repository.base_data_revision(site_id)
            infra = self.base_query.infrastructure(site_id)
            assets = {d.device_uuid: d for n in infra.nodes for d in n.devices}
            assets.update({d.device_uuid: d for d in infra.unassociated_devices})
            nodes = {n.uid: n for n in infra.nodes}
            records = (
                RailRelationshipRepository(self.paths)
                .list_current(site_id, at_time=at_time)
                .items
            )
            result = {}
            for uid, fallback in defaults.items():
                asset = assets.get(uid)
                related = [r for r in records if uid in (r.source_uid, r.target_uid)]
                physical = [
                    (n, d)
                    for n in infra.nodes
                    if n.kind != "section"
                    for d in n.devices
                    if d.device_uuid == uid
                ]
                if at_time:
                    physical = [
                        (nodes[r.source_uid], asset)
                        for r in related
                        if r.relationship_type in {"device_node", "train_mr"}
                        and r.source_uid in nodes
                    ]
                ctx = fallback.model_copy(
                    update=dict(
                        available=True,
                        line_id=site_id,
                        line_name=infra.line_name,
                        device_name=asset.name if asset else "",
                        device_type=asset.device_type if asset else "",
                        relationship_revision=before,
                        identity_status="confirmed"
                        if asset or related
                        else "unconfirmed",
                        affiliation_status="unassociated" if asset else "not_found",
                        reason_code="",
                    )
                )
                if len(physical) > 1:
                    ctx.affiliation_status = "conflict"
                    ctx.reason_code = "MULTIPLE_PHYSICAL_NODES"
                elif physical:
                    node, dev = physical[0]
                    ctx.node_uid, ctx.node_type, ctx.node_code, ctx.node_name = (
                        node.uid,
                        node.kind,
                        node.code,
                        node.name,
                    )
                    ctx.role = dev.role if dev else ""
                    ctx.station_id = (
                        node.station.id
                        if node.station
                        else node.uid
                        if node.kind == "station"
                        else ""
                    )
                    ctx.station_name = node.name if node.kind == "station" else ""
                    ctx.project_ids = (
                        [p.project_id for p in node.projects] if not at_time else []
                    )
                    ctx.project_names = (
                        [
                            " ".join(v for v in (p.stage, p.name) if v)
                            for p in node.projects
                        ]
                        if not at_time
                        else []
                    )
                    ctx.affiliation_status = "associated"
                for r in related:
                    if r.relationship_type == "device_section":
                        node = nodes.get(r.target_uid)
                        ctx.section_ids.append(r.target_uid)
                        ctx.service_sections.append(
                            (node.name if node else r.target_name or r.target_uid)
                            if not at_time
                            else r.target_name or r.target_uid
                        )
                    elif r.relationship_type == "ac_service":
                        node = nodes.get(r.target_uid)
                        ctx.service_stations.append(
                            (node.name if node else r.target_name or r.target_uid)
                            if not at_time
                            else r.target_name or r.target_uid
                        )
                    elif r.relationship_type in {"device_node", "train_mr"}:
                        ctx.role = str(
                            r.values.get("engineering_role")
                            or r.values.get("position")
                            or ctx.role
                        )
                        ctx.physical_location = str(
                            r.values.get("installation_location") or ""
                        )
                        if at_time:
                            ctx.node_uid = r.source_uid
                            ctx.node_name = r.source_name or r.source_uid
                            ctx.station_name = (
                                ctx.node_name if ctx.node_type == "station" else ""
                            )
                    ctx.service_scope.append(
                        dict(
                            relationship_id=r.relationship_id,
                            relationship_type=r.relationship_type,
                            source_uid=r.source_uid,
                            target_uid=r.target_uid,
                            target_station_id=(nodes[r.target_uid].station.id if r.target_uid in nodes and nodes[r.target_uid].station and not at_time else ""),
                            target_name=(
                                nodes[r.target_uid].name
                                if r.target_uid in nodes and not at_time
                                else r.target_name
                            ),
                            effective_from=r.effective_from,
                            effective_to=r.effective_to,
                        )
                    )
                if at_time and ctx.node_uid:
                    for r in records:
                        if (
                            r.relationship_type == "node_project"
                            and r.source_uid == ctx.node_uid
                        ):
                            ctx.project_ids.append(r.target_uid)
                            ctx.project_names.append(r.target_name or r.target_uid)
                if at_time:
                    if ctx.affiliation_status != "conflict":
                        ctx.affiliation_status = (
                            "historical" if related else "unconfirmed"
                        )
                        ctx.reason_code = (
                            "" if related else "HISTORICAL_RELATION_NOT_RECORDED"
                        )
                    event_names = [
                        r.target_name
                        if r.relationship_type in {"device_node", "train_mr"}
                        else r.source_name
                        for r in related
                    ]
                    ctx.device_name = next((name for name in event_names if name), "")
                elif related and ctx.affiliation_status in {
                    "unassociated",
                    "not_found",
                }:
                    ctx.affiliation_status = "associated"
                result[uid] = ctx
            after = self.base_query.repository.base_data_revision(site_id)
            if before != after or expected_revision and after != expected_revision:
                return {
                    k: v.model_copy(
                        update=dict(
                            available=False,
                            affiliation_status="stale",
                            reason_code="ENGINEERING_REVISION_CONFLICT",
                        )
                    )
                    for k, v in result.items()
                }
            return result
        except Exception:
            # Context must never prevent loading independently owned runtime evidence.
            return defaults

    def points(self, site_id, point_ids):
        ids = list(dict.fromkeys(v for v in point_ids if v))
        result = {
            uid: DeviceEngineeringContextDTO(
                point_id=uid, reason_code="AP_CONTEXT_UNAVAILABLE"
            )
            for uid in ids
        }
        if not ids:
            return result
        try:
            before = self.base_query.repository.base_data_revision(site_id)
            points = self.base_query.list_ap_location_items(site_id)
            infra = self.base_query.infrastructure(site_id)
            stations = {n.station.id: n for n in infra.nodes if n.station}
            for uid in ids:
                matches = [
                    p
                    for p in points
                    if p.id == uid
                    or p.identity_entity_id
                    and p.identity_entity_id == uid
                ]
                if len(matches) > 1:
                    result[uid] = DeviceEngineeringContextDTO(
                        point_id=uid,
                        available=True,
                        affiliation_status="conflict",
                        reason_code="AP_POINT_AMBIGUOUS",
                    )
                elif matches:
                    point = matches[0]
                    node = stations.get(point.station_id)
                    result[uid] = DeviceEngineeringContextDTO(
                        point_id=point.id,
                        identity_entity_id=point.identity_entity_id,
                        device_name=point.name,
                        available=True,
                        affiliation_status="associated",
                        identity_status=point.identity_match_status,
                        line_id=site_id,
                        line_name=point.line_name,
                        station_id=point.station_id,
                        station_name=point.station,
                        section_ids=[point.section_id] if point.section_id else [],
                        service_sections=[point.section] if point.section else [],
                        node_uid=node.uid if node else "",
                        node_name=node.name if node else "",
                        node_type=node.kind if node else "",
                        project_ids=[p.project_id for p in node.projects]
                        if node
                        else [],
                        project_names=[p.name for p in node.projects] if node else [],
                        relationship_revision=before,
                        context_updated_at=datetime.now(timezone.utc).isoformat(),
                    )
                else:
                    result[uid] = DeviceEngineeringContextDTO(
                        point_id=uid,
                        available=True,
                        affiliation_status="unconfirmed",
                        reason_code="STABLE_AP_POINT_NOT_FOUND",
                    )
            if self.base_query.repository.base_data_revision(site_id) != before:
                return {
                    uid: ctx.model_copy(
                        update=dict(
                            available=False,
                            affiliation_status="stale",
                            reason_code="ENGINEERING_REVISION_CONFLICT",
                        )
                    )
                    for uid, ctx in result.items()
                }
            return result
        except Exception:
            return {
                uid: DeviceEngineeringContextDTO(
                    point_id=uid,
                    affiliation_status="unavailable",
                    reason_code="ENGINEERING_CONTEXT_QUERY_FAILED",
                )
                for uid in ids
            }

    def one(self, site_id, device_uuid, **kwargs):
        if not device_uuid:
            return DeviceEngineeringContextDTO(
                reason_code="STABLE_DEVICE_ID_MISSING", affiliation_status="unconfirmed"
            )
        return self.contexts(site_id, [device_uuid], **kwargs)[device_uuid]
