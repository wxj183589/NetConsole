from __future__ import annotations

import os
from pathlib import Path
from zipfile import ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from openpyxl import Workbook
from PySide6.QtWidgets import QApplication

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.snmp_models import DeviceSnmpProfileResult, SnmpProfile, SnmpSetRequest
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.global_mib_repository import GlobalMibRepository
from netconsole.repositories.site_snmp_repository import SiteSnmpRepository
from netconsole.services.comware_version_service import parse_comware_version
from netconsole.services.mib_product_reference_compare_service import MibProductReferenceCompareService
from netconsole.services.mib_resource_service import MibResourceService
from netconsole.services.snmp_recommend_service import SnmpRecommendService
from netconsole.services.snmp_client import _encode_snmp_value, normalize_oid
from netconsole.services.snmp_query_service import SnmpQueryService
from netconsole.ui.pages.snmp_center_page import SnmpCenterPage


def _qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_snmp_center_initializes_global_and_site_databases(tmp_path: Path):
    paths = PathResolver(tmp_path)
    paths.ensure_global_mib_dirs()
    paths.ensure_site_snmp_dirs("demo")
    global_repo = GlobalMibRepository(paths.global_mib_db_path())
    site_repo = SiteSnmpRepository(paths.site_snmp_db_path("demo"))

    global_repo.initialize()
    site_repo.initialize()

    dictionaries = global_repo.list_dictionary_sets()
    templates = global_repo.list_templates()
    objects = global_repo.list_objects("sysName")

    assert paths.global_mib_db_path().exists()
    assert paths.site_snmp_db_path("demo").exists()
    assert any(item["name"] == "内置通用字典" for item in dictionaries)
    assert any(item["template_name"] == "系统信息" for item in templates)
    assert objects[0]["oid"] == "1.3.6.1.2.1.1.5"


def test_mib_import_indexes_objects_and_deduplicates_by_hash(tmp_path: Path):
    paths = PathResolver(tmp_path)
    service = MibResourceService(paths)
    mib_file = tmp_path / "TEST-MIB.mib"
    mib_file.write_text(
        """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    enterprises FROM SNMPv2-SMI;

testRoot OBJECT IDENTIFIER ::= { enterprises 99999 }

testScalar OBJECT-TYPE
    SYNTAX      INTEGER { up(1), down(2) }
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Test scalar"
    ::= { testRoot 1 }
END
""".strip(),
        encoding="utf-8",
    )

    first = service.import_paths([mib_file], vendor="TestVendor")
    second = service.import_paths([mib_file], vendor="TestVendor")
    repo = GlobalMibRepository(paths.global_mib_db_path())
    objects = repo.list_objects("testScalar")

    assert first.imported == 1
    assert second.duplicated == 1
    assert objects[0]["module_name"] == "TEST-MIB"
    assert objects[0]["oid"] == "1.3.6.1.4.1.99999.1"
    assert objects[0]["enum_map_json"] == '{"1": "up", "2": "down"}'


def test_batch_import_resolves_dependencies_by_module_definition_and_suffix(tmp_path: Path):
    paths = PathResolver(tmp_path)
    service = MibResourceService(paths)
    archive = tmp_path / "H3C-V9-V7-Comware_MIB-20260610.zip"
    with ZipFile(archive, "w") as package:
        package.writestr(
            "rfc2578.sm2",
            """
SNMPv2-SMI DEFINITIONS ::= BEGIN
enterprises OBJECT IDENTIFIER ::= { private 1 }
END
""".strip(),
        )
        package.writestr(
            "hh3c-oid.mib",
            """
HH3C-OID-MIB DEFINITIONS ::= BEGIN
IMPORTS enterprises FROM SNMPv2-SMI;
hh3c OBJECT IDENTIFIER ::= { enterprises 25506 }
END
""".strip(),
        )
        package.writestr(
            "mesh.txt",
            """
HH3C-DOT11S-MESH-MIB DEFINITIONS ::= BEGIN
IMPORTS hh3c FROM HH3C-OID-MIB;
hh3cDot11 OBJECT IDENTIFIER ::= { hh3c 2 }
hh3cDot11sMesh OBJECT IDENTIFIER ::= { hh3cDot11 75 }
hh3cDot11sMeshLinkStatusTable OBJECT-TYPE
    SYNTAX SEQUENCE OF MeshEntry
    MAX-ACCESS not-accessible
    STATUS current
    DESCRIPTION "Mesh table"
    ::= { hh3cDot11sMesh 11 }
END
""".strip(),
        )
        package.writestr("readme.txt", "not a mib")

    report = service.import_paths([archive])
    repo = GlobalMibRepository(paths.global_mib_db_path())
    modules = repo.list_modules()
    packages = repo.list_source_packages()
    templates = repo.list_templates()

    assert report.failed == 0
    assert {row["module_name"] for row in modules} >= {"SNMPv2-SMI", "HH3C-OID-MIB", "HH3C-DOT11S-MESH-MIB"}
    assert any(row["package_name"] == "H3C-Comware-V7V9-20260610" for row in packages)
    assert not repo.list_missing_dependency_summary()
    assert any(row["template_name"] == "Mesh 链路状态模板" for row in templates)


def test_builtin_h3c_initialization_registers_packages_once(tmp_path: Path):
    builtin_dir = tmp_path / "resources" / "builtin_mibs" / "h3c" / "comware_v5_20210918"
    builtin_dir.mkdir(parents=True)
    archive = builtin_dir / "H3C-V5-Comware_MIB-20210918.zip"
    with ZipFile(archive, "w") as package:
        package.writestr(
            "rfc2578.sm2",
            "SNMPv2-SMI DEFINITIONS ::= BEGIN\nenterprises OBJECT IDENTIFIER ::= { private 1 }\nEND",
        )
        package.writestr(
            "hh3c-oid.mib",
            "HH3C-OID-MIB DEFINITIONS ::= BEGIN\nIMPORTS enterprises FROM SNMPv2-SMI;\nhh3c OBJECT IDENTIFIER ::= { enterprises 25506 }\nEND",
        )

    paths = PathResolver(tmp_path)
    service = MibResourceService(paths)
    first = service.initialize_builtin_resources()
    second = service.initialize_builtin_resources()
    repo = GlobalMibRepository(paths.global_mib_db_path())
    packages = repo.list_source_packages()

    assert first.imported == 2
    assert second.imported == 0
    assert len(packages) == 1
    assert packages[0]["source_type"] == "builtin_h3c_comware_package"
    assert packages[0]["version_line"] == "V5"


def test_comware_release_and_product_reference_recommendation(tmp_path: Path):
    paths = PathResolver(tmp_path)
    repo = GlobalMibRepository(paths.global_mib_db_path())
    repo.initialize()
    xlsx = tmp_path / "20260522-H3C 无线控制器产品 MIB参考-R16xx-6W100.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "对象"
    sheet.append(["MIB模块", "对象名称", "OID", "中文含义", "实现规格", "支持情况"])
    sheet.append(["HH3C-DOT11S-MESH-MIB", "hh3cDot11sMeshNbrRSSI", "1.3.6.1.4.1.25506.2.75.11.3.3.1.11", "邻居 RSSI", "R16xx 支持", "支持读取"])
    workbook.save(xlsx)

    report = MibResourceService(paths, repo).import_paths([xlsx])
    profile = DeviceSnmpProfileResult(
        device_name="NBDT12HX-WX3540X-AC1",
        vendor="H3C",
        device_type="AC",
        model="WX3540X",
        system="Comware",
        system_version="9.1.081",
        os_family="Comware",
        os_major="V9",
        release="1608P01",
        release_number="1608",
        release_patch="P01",
        release_series="R16xx",
        sys_descr="H3C Comware Software, Version 9.1.081, Release 1608P01",
    )
    recommendations = SnmpRecommendService(repo).recommend_product_references(Device(name="NBDT12HX-WX3540X-AC1", device_vendor="H3C", device_type="AC"), profile)
    override = repo.find_product_object_override(module_name="HH3C-DOT11S-MESH-MIB", object_name="hh3cDot11sMeshNbrRSSI", numeric_oid="1.3.6.1.4.1.25506.2.75.11.3.3.1.11")
    parsed = parse_comware_version(profile.sys_descr)

    assert report.imported == 1
    assert parsed.software_version == "9.1.081"
    assert parsed.release == "1608P01"
    assert parsed.release_series == "R16xx"
    assert recommendations[0].reference_name == "20260522-H3C 无线控制器产品 MIB参考-R16xx-6W100"
    assert "R16xx" in "；".join(recommendations[0].reasons)
    assert override is not None
    assert override["implementation_spec"] == "R16xx 支持"


def test_product_reference_compare_matches_by_oid_and_normalizes_category_numbers(tmp_path: Path):
    paths = PathResolver(tmp_path)
    repo = GlobalMibRepository(paths.global_mib_db_path())
    repo.initialize()

    left_xlsx = tmp_path / "20251226-H3C 无线控制器产品 MIB参考-R12xx_E12xx-6W101.xlsx"
    right_xlsx = tmp_path / "20260522-H3C 无线控制器产品 MIB参考-R16xx-6W100.xlsx"

    left_book = Workbook()
    left_sheet = left_book.active
    left_sheet.title = "表节点"
    left_sheet.append(["分册名", "模块名", "MIB文件名", "根节点", "父节点名称", "功能描述", "操作支持情况", "子节点名称及OID", "最大访问权限", "数据类型", "有效范围", "含义", "实现规格"])
    left_sheet.append(["11-WLAN", "01-HH3C-DOT11S-MESH-MIB", "hh3c-dot11s-mesh.mib", "hh3cDot11sMesh", "hh3cDot11sMeshNbrStatusTable", "邻居 RSSI", "读取约束：支持", "hh3cDot11sMeshNbrRSSI（1.3.6.1.4.1.25506.2.75.11.3.3.1.11）", "read-only", "Integer32", "-100..0", "旧 RSSI", "R12xx 支持"])
    left_book.save(left_xlsx)

    right_book = Workbook()
    right_sheet = right_book.active
    right_sheet.title = "表节点"
    right_sheet.append(["分册名", "模块名", "MIB文件名", "根节点", "父节点名称", "功能描述", "操作支持情况", "子节点名称及OID", "最大访问权限", "数据类型", "有效范围", "含义", "实现规格"])
    right_sheet.append(["13-WLAN", "13-HH3C-DOT11S-MESH-MIB", "hh3c-dot11s-mesh.mib", "hh3cDot11sMesh", "hh3cDot11sMeshNbrStatusTable", "邻居 RSSI", "读取约束：支持", "hh3cDot11sMeshNbrRSSI（1.3.6.1.4.1.25506.2.75.11.3.3.1.11）", "read-only", "Integer32", "-120..0", "新 RSSI", "R16xx 支持"])
    right_sheet.append(["13-WLAN", "13-HH3C-DOT11S-MESH-MIB", "hh3c-dot11s-mesh.mib", "hh3cDot11sMesh", "hh3cDot11sMeshLinkStatusTable", "链路状态", "读取约束：支持", "hh3cDot11sMeshLinkStatus（1.3.6.1.4.1.25506.2.75.11.3.1.1.5）", "read-only", "Integer32", "1..2", "链路状态", "R16xx 新增"])
    right_book.save(right_xlsx)

    report = MibResourceService(paths, repo).import_paths([left_xlsx, right_xlsx])
    references = repo.list_product_references()
    left_id = next(int(row["id"]) for row in references if row["release_series"] == "R12xx,E12xx")
    right_id = next(int(row["id"]) for row in references if row["release_series"] == "R16xx")

    result = MibProductReferenceCompareService(repo).compare(left_id, right_id)
    stored_rows = repo.list_product_reference_compare_results(left_id, right_id, limit=1000)
    right_objects = repo.list_product_object_overrides(right_id)

    assert report.imported == 2
    assert any(row["module_name"] == "HH3C-DOT11S-MESH-MIB" for row in right_objects)
    assert result.summary["objects_added"] == 1
    assert any(row["diff_type"] == "category_changed" and row["field_name"] == "category_name" for row in stored_rows)
    assert any(row["diff_type"] == "changed" and row["field_name"] == "取值范围" for row in stored_rows)
    assert any(row["diff_type"] == "added" and row["numeric_oid"] == "1.3.6.1.4.1.25506.2.75.11.3.1.1.5" for row in stored_rows)


def test_snmp_center_hides_reference_compare_and_standalone_query_tabs(tmp_path: Path):
    _qt_app()
    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("demo")
    repository = DeviceRepository(paths.site_db_path("demo"))

    page = SnmpCenterPage(repository, I18n(), "demo", paths)
    titles = [page.tabs.tabText(index) for index in range(page.tabs.count())]

    assert "产品参考对比" not in titles
    assert "SNMP 查询工具" not in titles
    assert "设备字典推荐" not in titles
    assert any("MIB" in title and "浏览" in title for title in titles)


def test_mib_browser_builds_selected_module_tree(tmp_path: Path):
    _qt_app()
    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("demo")
    mib_file = tmp_path / "TEST-MIB.mib"
    mib_file.write_text(
        """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    enterprises FROM SNMPv2-SMI;

testRoot OBJECT IDENTIFIER ::= { enterprises 99998 }

testTable OBJECT-TYPE
    SYNTAX      SEQUENCE OF TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "Test table"
    ::= { testRoot 1 }

testEntry OBJECT-TYPE
    SYNTAX      TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "Test entry"
    INDEX       { testIndex }
    ::= { testTable 1 }

TestEntry ::= SEQUENCE {
    testIndex INTEGER,
    testValue INTEGER
}

testIndex OBJECT-TYPE
    SYNTAX      INTEGER
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Test index"
    ::= { testEntry 1 }

testValue OBJECT-TYPE
    SYNTAX      INTEGER
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Test value"
    ::= { testEntry 2 }
END
""".strip(),
        encoding="utf-8",
    )
    MibResourceService(paths).import_paths([mib_file])
    global_repo = GlobalMibRepository(paths.global_mib_db_path())
    module = next(row for row in global_repo.list_modules() if row["module_name"] == "TEST-MIB")
    rows = global_repo.list_objects(module_id=int(module["id"]), limit=100)

    page = SnmpCenterPage(DeviceRepository(paths.site_db_path("demo")), I18n(), "demo", paths)
    page.browser_page.module_filter.addItem("TEST-MIB", int(module["id"]))
    page.browser_page.module_filter.setCurrentIndex(0)
    page.browser_page._build_module_tree(int(module["id"]), rows)
    root = page.browser_page.tree.topLevelItem(0)
    root_names = [root.child(index).text(0) for index in range(root.childCount())]
    table = root.child(root_names.index("testRoot")).child(0)

    assert root.text(0) == "TEST-MIB"
    assert "testRoot" in root_names
    assert table.text(0) == "testTable"
    assert table.child(0).text(0) == "testEntry"


def test_snmp_client_requires_numeric_oid_for_final_query():
    assert normalize_oid(".1.3.6.1.2.1.1.5.0") == "1.3.6.1.2.1.1.5.0"
    assert normalize_oid("sysName.0") == "1.3.6.1.2.1.1.5.0"
    with pytest.raises(ValueError, match="数字 OID"):
        normalize_oid("sysName")


def test_snmp_set_is_disabled_by_default_and_logged(tmp_path: Path):
    paths = PathResolver(tmp_path)
    repo = SiteSnmpRepository(paths.site_snmp_db_path("demo"))
    repo.initialize()
    request = SnmpSetRequest(profile=SnmpProfile(host="127.0.0.1", community_rw="private"), oid="1.3.6.1.2.1.1.5.0", data_type="DisplayString", value="demo")

    result = SnmpQueryService(repo).set_value(request)

    assert result.status == "cancelled"
    assert repo.snmp_set_enabled() is False
    history = repo.list_set_history()
    assert history[0]["oid"] == "1.3.6.1.2.1.1.5.0"
    assert history[0]["status"] == "cancelled"


def test_snmp_set_requires_rw_community_when_enabled(tmp_path: Path):
    paths = PathResolver(tmp_path)
    repo = SiteSnmpRepository(paths.site_snmp_db_path("demo"))
    repo.initialize()
    repo.set_snmp_set_enabled(True)
    request = SnmpSetRequest(profile=SnmpProfile(host="127.0.0.1", community_ro="public", community_rw=""), oid="1.3.6.1.2.1.1.5.0", data_type="DisplayString", value="demo")

    result = SnmpQueryService(repo).set_value(request)

    assert result.status == "auth_failed"
    assert "community_rw" in result.error_message


def test_snmp_set_value_encoder_validates_basic_types():
    assert _encode_snmp_value("Integer", "12") == b"\x02\x01\x0c"
    assert _encode_snmp_value("HexString", "0x01020AFF") == b"\x04\x04\x01\x02\n\xff"
    assert _encode_snmp_value("IpAddress", "192.168.1.1") == b"\x40\x04\xc0\xa8\x01\x01"
    with pytest.raises(ValueError):
        _encode_snmp_value("Gauge32", "-1")
