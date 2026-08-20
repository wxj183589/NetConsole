from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import uuid
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path
from urllib.parse import quote, unquote

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version
from license_expression import ExpressionError, get_spdx_licensing

from scripts.build.python_runtime_contract import (
    assert_current_python_runtime,
    load_python_runtime_version,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NOTICE_RELATIVE = Path("src/netconsole/assets/open_source_notices.json")
RUNTIME_REQUIREMENTS = "requirements-runtime.txt"
RUNTIME_CONSTRAINTS = "constraints.txt"
UNKNOWN_LICENSES = {
    "",
    "unknown",
    "unknown license",
    "not declared",
    "未在包元数据中声明",
}
PURL_PATTERN = re.compile(r"^pkg:(pypi|npm|generic)/([^@?#]+)@([^?#]+)$")
CYCLONEDX_SPEC_VERSION = "1.5"
SPDX_LICENSING = get_spdx_licensing()
REQUIRED_NOTICE_NAMES = (
    "Python",
    "Electron",
    "Chromium",
    "Node.js",
    "fping",
    "iPerf3 Windows x64 Cygwin dynamic-auth",
    "cJSON (embedded in iPerf3)",
    "Cygwin Runtime (fping bundle)",
    "Cygwin Runtime (iPerf3 bundle)",
    "OpenSSL Runtime (iPerf3 bundle)",
    "zlib Runtime (iPerf3 bundle)",
    "PyInstaller",
    "pyinstaller-hooks-contrib",
)
PACKAGED_PYTHON_DISTRIBUTIONS = ("pyinstaller", "pyinstaller-hooks-contrib")
PACKAGED_PYTHON_LICENSES = {
    "pyinstaller": (
        "licenses/PYINSTALLER_COPYING.txt",
        "licenses/COPYING.txt",
        "dcf75fdb959db1e3b41c0f8505069d2ece781b5ec6b3d0a4d30975cfc6580245",
    ),
    "pyinstaller-hooks-contrib": (
        "licenses/PYINSTALLER_HOOKS_CONTRIB_LICENSE.txt",
        "licenses/LICENSE",
        "91d0baaff00773038e72c0a1fc9d5d2d38706b7a2b9c04f34296608f931b9cd0",
    ),
}


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", str(value).strip().casefold())


def read_notice_entries(path: Path) -> list[dict[str, object]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"开源 Notice 必须是数组：{path}")
    return [item for item in raw if isinstance(item, dict)]


def validate_notice_file(
    path: Path,
    *,
    required_names: tuple[str, ...] = REQUIRED_NOTICE_NAMES,
) -> tuple[str, ...]:
    try:
        entries = read_notice_entries(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return (f"无法读取开源 Notice：{path}：{exc}",)
    errors: list[str] = []
    names: set[str] = set()
    purls: set[str] = set()
    for index, item in enumerate(entries):
        name = str(item.get("name") or "").strip()
        version = str(item.get("version") or "").strip()
        license_text = str(item.get("license") or "").strip()
        purl = str(item.get("purl") or "").strip()
        if not name:
            errors.append(f"Notice 第 {index + 1} 项缺少 name")
            continue
        normalized_name = normalize_name(name)
        if normalized_name in names:
            errors.append(f"Notice 组件重复：{name}")
        names.add(normalized_name)
        if not version:
            errors.append(f"Notice 组件缺少 version：{name}")
        if (
            not license_text
            or license_text.casefold() in UNKNOWN_LICENSES
            or str(item.get("status") or "").casefold() == "blocked"
        ):
            errors.append(f"Notice 组件许可证未知或被阻塞：{name}")
        if not str(item.get("scope") or "").strip():
            errors.append(f"Notice 组件缺少 scope：{name}")
        license_files = _notice_license_files(item)
        if (
            str(item.get("scope") or "").strip()
            in {
                "runtime-tool",
                "packaged-build-runtime",
            }
            and not license_files
        ):
            errors.append(f"Notice 随包组件缺少许可证文件：{name}")
        for license_file in license_files:
            relative = Path(license_file)
            if relative.is_absolute() or ".." in relative.parts:
                errors.append(f"Notice 许可证路径越界：{name}: {license_file}")
        purl_error = _validate_purl(purl)
        if purl_error:
            errors.append(f"Notice 组件 PURL 无效：{name}: {purl_error}")
        elif ecosystem_error := _notice_ecosystem_error(item, purl):
            errors.append(f"Notice 组件 PURL 生态错误：{name}: {ecosystem_error}")
        elif purl_version_error := _purl_version_error(purl, version):
            errors.append(f"Notice 组件 PURL 版本不一致：{name}: {purl_version_error}")
        elif purl in purls:
            errors.append(f"Notice 组件 PURL 重复：{purl}")
        else:
            purls.add(purl)
        artifact_path = str(item.get("artifact_path") or "").strip()
        sha256 = str(item.get("sha256") or "").strip().casefold()
        if bool(artifact_path) != bool(sha256):
            errors.append(f"Notice 组件 artifact_path/sha256 必须成对出现：{name}")
        elif sha256 and not re.fullmatch(r"[0-9a-f]{64}", sha256):
            errors.append(f"Notice 组件 sha256 无效：{name}")
        if (
            normalized_name in {"pytest", "pyinstaller", "nuitka"}
            and str(item.get("scope") or "runtime") == "runtime"
        ):
            errors.append(f"测试/构建工具不得伪装成产品运行时：{name}")
    for required in required_names:
        if normalize_name(required) not in names:
            errors.append(f"Notice 缺少必要组件：{required}")
    return tuple(errors)


def validate_sbom(
    path: Path,
    *,
    required_names: tuple[str, ...] = REQUIRED_NOTICE_NAMES,
    required_python_components: Mapping[str, str] | None = None,
    project_root: Path = PROJECT_ROOT,
) -> tuple[str, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (f"无法读取 SBOM：{path}：{exc}",)
    if not isinstance(payload, dict) or payload.get("bomFormat") != "CycloneDX":
        return (f"SBOM 不是 CycloneDX 文档：{path}",)
    errors: list[str] = []
    if payload.get("specVersion") != CYCLONEDX_SPEC_VERSION:
        errors.append(f"SBOM specVersion 必须是 {CYCLONEDX_SPEC_VERSION}")
    if not isinstance(payload.get("version"), int) or payload.get("version", 0) < 1:
        errors.append("SBOM version 必须是正整数")
    serial_number = str(payload.get("serialNumber") or "")
    try:
        if not serial_number.startswith("urn:uuid:"):
            raise ValueError
        uuid.UUID(serial_number.removeprefix("urn:uuid:"))
    except ValueError:
        errors.append("SBOM serialNumber 必须是 urn:uuid")
    metadata_component = (
        payload.get("metadata", {}).get("component")
        if isinstance(payload.get("metadata"), dict)
        else None
    )
    if not isinstance(metadata_component, dict) or not all(
        str(metadata_component.get(field) or "").strip()
        for field in ("type", "name", "version", "bom-ref")
    ):
        errors.append("SBOM metadata.component 缺少 type/name/version/bom-ref")
    elif metadata_purl_error := _validate_purl(
        str(metadata_component.get("bom-ref") or "")
    ):
        errors.append(f"SBOM metadata.component bom-ref 无效：{metadata_purl_error}")
    components = payload.get("components")
    if not isinstance(components, list):
        return tuple((*errors, f"SBOM 缺少 components：{path}"))
    names: set[str] = set()
    bom_refs: set[str] = set()
    python_components: dict[str, str] = {}
    for item in components:
        if not isinstance(item, dict):
            errors.append("SBOM component 不是对象")
            continue
        name = str(item.get("name") or "").strip()
        names.add(normalize_name(name))
        bom_ref = str(item.get("bom-ref") or "").strip()
        purl = str(item.get("purl") or "").strip()
        licenses = item.get("licenses")
        if (
            not name
            or not str(item.get("version") or "").strip()
            or not str(item.get("type") or "").strip()
            or not bom_ref
            or not isinstance(licenses, list)
            or not licenses
        ):
            errors.append(
                f"SBOM component 缺少 type/name/version/bom-ref/license：{name or '<unknown>'}"
            )
            continue
        if bom_ref in bom_refs:
            errors.append(f"SBOM component bom-ref 重复：{bom_ref}")
        bom_refs.add(bom_ref)
        purl_error = _validate_purl(purl)
        if purl_error:
            errors.append(f"SBOM 组件 PURL 无效：{name}: {purl_error}")
        elif bom_ref != purl:
            errors.append(f"SBOM 组件 bom-ref 必须与 PURL 一致：{name}")
        elif purl_version_error := _purl_version_error(
            purl, str(item.get("version") or "")
        ):
            errors.append(f"SBOM 组件 PURL 版本不一致：{name}: {purl_version_error}")
        else:
            purl_match = PURL_PATTERN.fullmatch(purl)
            if purl_match and purl_match.group(1) == "pypi":
                python_name = normalize_name(unquote(purl_match.group(2)))
                if python_name in python_components:
                    errors.append(f"SBOM Python 组件重复：{python_name}")
                else:
                    python_components[python_name] = str(item.get("version") or "")
        for license_item in licenses:
            license_text = ""
            if isinstance(license_item, dict):
                license_data = license_item.get("license")
                if isinstance(license_data, dict):
                    license_text = str(
                        license_data.get("id") or license_data.get("name") or ""
                    ).strip()
                else:
                    license_text = str(license_item.get("expression") or "").strip()
            if not license_text or license_text.casefold() in UNKNOWN_LICENSES:
                errors.append(f"SBOM 组件许可证未知：{name}")
    for required in required_names:
        if normalize_name(required) not in names:
            errors.append(f"SBOM 缺少必要组件：{required}")
    if required_python_components is None:
        try:
            required_python_components = required_python_component_versions(
                project_root
            )
        except (OSError, ValueError) as exc:
            errors.append(f"无法解析锁定 Python 运行闭包：{exc}")
            required_python_components = {}
    expected_python = {
        normalize_name(name): str(version)
        for name, version in required_python_components.items()
    }
    for name in sorted(expected_python.keys() | python_components.keys()):
        expected_version = expected_python.get(name)
        actual_version = python_components.get(name)
        if expected_version is None:
            errors.append(f"SBOM 包含未批准 Python 组件：{name}=={actual_version}")
        elif actual_version is None:
            errors.append(f"SBOM 缺少锁定 Python 组件：{name}=={expected_version}")
        elif actual_version != expected_version:
            errors.append(
                f"SBOM Python 组件版本不一致：{name} "
                f"expected={expected_version}, actual={actual_version}"
            )
    return tuple(errors)


def write_runtime_sbom(
    output_path: Path,
    *,
    project_root: Path = PROJECT_ROOT,
    packaged_python_components: Mapping[str, str] | None = None,
) -> Path:
    project_root = Path(project_root).resolve()
    notice_path = project_root / NOTICE_RELATIVE
    notices = read_notice_entries(notice_path)
    _verify_notice_fact_sources(notices, project_root)
    notice_map = {
        normalize_name(str(item.get("name"))): item
        for item in notices
        if item.get("name")
    }
    distributions = _installed_distributions()
    runtime_distributions = _runtime_dependency_distributions(
        project_root,
        distributions=distributions,
    )
    runtime_versions = {
        name: distribution.version
        for name, distribution in runtime_distributions.items()
    }
    packaged_distributions: dict[str, metadata.Distribution] = {}
    for name in PACKAGED_PYTHON_DISTRIBUTIONS:
        distribution = distributions.get(normalize_name(name))
        if distribution is None:
            raise ValueError(f"构建环境缺少随包组件：{name}")
        packaged_distributions[normalize_name(name)] = distribution
    allowed_python_versions = {
        **runtime_versions,
        **{
            name: distribution.version
            for name, distribution in packaged_distributions.items()
        },
    }
    _validate_packaged_python_versions(allowed_python_versions, project_root)
    if packaged_python_components is None:
        required_python_versions = allowed_python_versions
    else:
        required_python_versions = {
            normalize_name(name): str(version)
            for name, version in packaged_python_components.items()
        }
        for name in sorted(
            set(required_python_versions) | set(allowed_python_versions)
        ):
            actual = required_python_versions.get(name)
            allowed = allowed_python_versions.get(name)
            if actual is not None and allowed != actual:
                raise ValueError(
                    f"制品 Python 组件不在批准运行闭包或版本不一致：{name}=={actual}"
                )
        missing_packaged = sorted(
            name
            for name in PACKAGED_PYTHON_DISTRIBUTIONS
            if normalize_name(name) not in required_python_versions
        )
        if missing_packaged:
            raise ValueError(
                "制品缺少 PyInstaller 随包组件：" + ", ".join(missing_packaged)
            )
    audit_runtime_inventory_with_cyclonedx(required_python_versions)
    components: dict[str, dict[str, object]] = {}
    available_distributions = {**runtime_distributions, **packaged_distributions}
    for key in sorted(required_python_versions):
        _add_distribution_component(
            key,
            available_distributions[key],
            components,
            notice_map,
        )

    python_notice = notice_map.get("python")
    if python_notice:
        components["python"] = _component_from_notice(python_notice, scope="required")
    for key, item in notice_map.items():
        if str(item.get("scope") or "") in {"electron", "runtime-tool"}:
            components[key] = _component_from_notice(item, scope="optional")

    version = _application_version(project_root)
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'netconsole:{version}')}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "NetConsole Backend",
                "version": version,
                "bom-ref": f"pkg:generic/netconsole-backend@{quote(version, safe='.-_~')}",
            }
        },
        "components": [components[key] for key in sorted(components)],
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    errors = validate_sbom(
        output_path,
        required_python_components=required_python_versions,
        project_root=project_root,
    )
    if errors:
        raise ValueError("生成的 SBOM 校验失败：" + "; ".join(errors))
    return output_path


def _installed_distributions() -> dict[str, metadata.Distribution]:
    result: dict[str, metadata.Distribution] = {}
    environment_paths = sorted(
        {
            str(Path(path).resolve())
            for path in (
                sysconfig.get_path("purelib"),
                sysconfig.get_path("platlib"),
            )
            if path
        }
    )
    for distribution in metadata.distributions(path=environment_paths):
        name = distribution.metadata.get("Name")
        if name:
            normalized = normalize_name(name)
            previous = result.get(normalized)
            if previous is not None and previous.version != distribution.version:
                raise ValueError(
                    f"当前 Python 环境存在重复版本：{name} "
                    f"{previous.version}/{distribution.version}"
                )
            result[normalized] = distribution
    return result


def _add_distribution_component(
    key: str,
    distribution: metadata.Distribution,
    components: dict[str, dict[str, object]],
    notice_map: dict[str, dict[str, object]],
) -> None:
    metadata_info = distribution.metadata
    override = notice_map.get(key, {})
    license_text = (
        str(override.get("license") or "").strip()
        or _license_from_tooling(distribution)
        or _license_from_metadata(metadata_info)
    )
    homepage = str(override.get("homepage") or "").strip() or _project_url(
        metadata_info
    )
    components[key] = _component(
        str(metadata_info.get("Name") or key),
        distribution.version,
        license_text or "UNKNOWN",
        homepage,
        "required",
    )


def _component_from_notice(item: dict[str, object], *, scope: str) -> dict[str, object]:
    return _component(
        str(item.get("name") or "unknown"),
        str(item.get("version") or "bundled"),
        str(item.get("license") or "UNKNOWN"),
        str(item.get("homepage") or ""),
        scope,
        purl=str(item.get("purl") or ""),
        sha256=str(item.get("sha256") or ""),
    )


def _component(
    name: str,
    version: str,
    license_text: str,
    homepage: str,
    scope: str,
    *,
    purl: str | None = None,
    sha256: str = "",
) -> dict[str, object]:
    component_purl = purl or _pypi_purl(name, version)
    component: dict[str, object] = {
        "type": "library",
        "name": name,
        "version": version,
        "bom-ref": component_purl,
        "purl": component_purl,
        "scope": scope,
        "licenses": [_license_choice(license_text)],
    }
    if sha256:
        component["hashes"] = [{"alg": "SHA-256", "content": sha256.casefold()}]
    if homepage:
        component["externalReferences"] = [{"type": "website", "url": homepage}]
    return component


def _license_choice(license_text: str) -> dict[str, object]:
    try:
        SPDX_LICENSING.parse(license_text, validate=True)
    except ExpressionError:
        return {"license": {"name": license_text}}
    if any(
        operator in license_text for operator in (" AND ", " OR ", " WITH ", "(", ")")
    ):
        return {"expression": license_text}
    return {"license": {"id": license_text}}


def _pypi_purl(name: str, version: str) -> str:
    return f"pkg:pypi/{quote(normalize_name(name), safe='.-_~')}@{quote(version, safe='.-_~+')}"


def _validate_purl(value: str) -> str:
    if not value:
        return "缺少 PURL"
    if any(character.isspace() for character in value):
        return "PURL 含空白字符"
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        return "PURL 百分号编码无效"
    match = PURL_PATTERN.fullmatch(value)
    if match is None:
        return "仅允许带版本的 pypi/npm/generic package-url"
    ecosystem, encoded_name, encoded_version = match.groups()
    try:
        name = unquote(encoded_name)
        version = unquote(encoded_version)
    except UnicodeError:
        return "PURL 百分号编码无效"
    if not name or not version:
        return "PURL name/version 不能为空"
    if ecosystem == "pypi" and ("/" in name or normalize_name(name) != name):
        return "PyPI PURL 名称必须使用规范化名称"
    return ""


def _purl_version_error(purl: str, version: str) -> str:
    match = PURL_PATTERN.fullmatch(purl)
    if match is None:
        return ""
    purl_version = unquote(match.group(3))
    return (
        "" if purl_version == version else f"expected={version}, actual={purl_version}"
    )


def _notice_ecosystem_error(item: dict[str, object], purl: str) -> str:
    name = normalize_name(str(item.get("name") or ""))
    scope = str(item.get("scope") or "").strip()
    ecosystem_match = PURL_PATTERN.fullmatch(purl)
    if ecosystem_match is None:
        return ""
    ecosystem = ecosystem_match.group(1)
    if name == "electron":
        expected = "npm"
    elif scope in {"runtime", "packaged-build-runtime"} and name != "python":
        expected = "pypi"
    else:
        expected = "generic"
    return "" if ecosystem == expected else f"expected={expected}, actual={ecosystem}"


def _verify_notice_fact_sources(
    notices: list[dict[str, object]], project_root: Path
) -> None:
    notice_by_name = {
        normalize_name(str(item.get("name") or "")): item
        for item in notices
        if item.get("name")
    }
    assert_current_python_runtime(project_root)
    expected_versions = {"python": load_python_runtime_version(project_root)}
    expected_versions.update(_electron_runtime_versions(project_root))
    installed = _installed_distributions()
    _validate_packaged_python_license_sources(
        notice_by_name,
        installed,
        project_root,
    )
    for item in notices:
        if str(item.get("scope") or "") not in {
            "runtime",
            "packaged-build-runtime",
        }:
            continue
        name = normalize_name(str(item.get("name") or ""))
        if name == "python":
            continue
        distribution = installed.get(name)
        if distribution is None:
            raise ValueError(
                f"Notice 运行时组件未安装：{item.get('name') or '<unknown>'}"
            )
        expected_versions[str(item.get("name"))] = distribution.version
    for name, expected in expected_versions.items():
        item = notice_by_name.get(normalize_name(name))
        actual = str(item.get("version") or "").strip() if item else ""
        if actual != expected:
            raise ValueError(
                f"Notice 版本与事实源不一致：{name} expected={expected}, actual={actual or '<missing>'}"
            )

    for item in notices:
        for relative in _notice_license_files(item):
            license_path = _project_fact_path(project_root, relative)
            if project_root not in license_path.parents or not license_path.is_file():
                raise ValueError(
                    f"Notice 许可证文件不存在或越界：{item.get('name') or '<unknown>'}: {relative}"
                )
        artifact_path = str(item.get("artifact_path") or "").strip()
        expected_sha256 = str(item.get("sha256") or "").strip().casefold()
        if not artifact_path and not expected_sha256:
            continue
        if not artifact_path or not expected_sha256:
            raise ValueError(
                f"Notice artifact_path/sha256 必须成对出现：{item.get('name') or '<unknown>'}"
            )
        artifact = _project_fact_path(project_root, artifact_path)
        if project_root not in artifact.parents or not artifact.is_file():
            raise ValueError(f"Notice 组件事实文件不存在或越界：{artifact_path}")
        actual_sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"Notice 组件 SHA-256 不一致：{item.get('name') or '<unknown>'}"
            )


def _project_fact_path(project_root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.parts and path.parts[0].casefold() == "tools":
        path = Path("resources") / path
    elif path.parts and path.parts[0].casefold() == "licenses":
        path = Path("src/netconsole/assets") / path
    return (project_root / path).resolve()


def _validate_packaged_python_license_sources(
    notice_by_name: Mapping[str, dict[str, object]],
    installed: Mapping[str, metadata.Distribution],
    project_root: Path,
) -> None:
    for name, (
        asset_relative,
        distribution_suffix,
        expected_sha256,
    ) in PACKAGED_PYTHON_LICENSES.items():
        notice = notice_by_name.get(name)
        if notice is None:
            raise ValueError(f"Notice 缺少随包组件许可证：{name}")
        if _notice_license_files(notice) != (asset_relative,):
            raise ValueError(f"Notice 随包组件许可证清单不精确：{name}")
        asset = _project_fact_path(project_root, asset_relative)
        if not asset.is_file():
            raise ValueError(f"随包组件许可证事实文件不存在：{asset_relative}")
        asset_bytes = asset.read_bytes()
        if hashlib.sha256(asset_bytes).hexdigest() != expected_sha256:
            raise ValueError(f"随包组件许可证事实文件哈希不一致：{name}")

        distribution = installed.get(name)
        if distribution is None:
            raise ValueError(f"构建环境缺少随包组件：{name}")
        candidates = [
            file
            for file in distribution.files or ()
            if str(file)
            .replace("\\", "/")
            .casefold()
            .endswith(distribution_suffix.casefold())
        ]
        if len(candidates) != 1:
            raise ValueError(f"随包组件许可证来源不唯一：{name}")
        installed_bytes = Path(distribution.locate_file(candidates[0])).read_bytes()
        if (
            hashlib.sha256(installed_bytes).hexdigest() != expected_sha256
            or installed_bytes != asset_bytes
        ):
            raise ValueError(f"随包组件许可证与锁定安装包不一致：{name}")


def _notice_license_files(item: dict[str, object]) -> tuple[str, ...]:
    values: list[str] = []
    notice_file = str(item.get("notice_file") or "").strip()
    if notice_file:
        values.append(notice_file)
    raw = item.get("license_files")
    if isinstance(raw, list):
        values.extend(str(value).strip() for value in raw if str(value).strip())
    return tuple(dict.fromkeys(values))


def _electron_runtime_versions(project_root: Path) -> dict[str, str]:
    package_path = project_root / "apps" / "desktop_electron" / "package.json"
    try:
        package_payload = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 Electron package.json：{exc}") from exc
    electron_version = str(
        package_payload.get("devDependencies", {}).get("electron") or ""
    ).strip()
    if not electron_version:
        raise ValueError("Electron package.json 缺少固定 electron 版本")
    result = {"Electron": electron_version}
    electron_dir = (
        project_root / "apps" / "desktop_electron" / "node_modules" / "electron"
    )
    try:
        executable_name = (
            (electron_dir / "path.txt").read_text(encoding="utf-8").strip()
        )
    except OSError:
        return result
    executable = (electron_dir / "dist" / executable_name).resolve()
    if not executable.is_file():
        return result
    environment = os.environ.copy()
    environment["ELECTRON_RUN_AS_NODE"] = "1"
    try:
        completed = subprocess.run(
            [str(executable), "-p", "JSON.stringify(process.versions)"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            env=environment,
        )
        runtime_versions = (
            json.loads(completed.stdout) if completed.returncode == 0 else {}
        )
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        runtime_versions = {}
    if runtime_versions:
        if str(runtime_versions.get("electron") or "") != electron_version:
            raise ValueError("Electron package.json 与 Electron runtime 版本不一致")
        for notice_name, runtime_name in (("Node.js", "node"), ("Chromium", "chrome")):
            version = str(runtime_versions.get(runtime_name) or "").strip()
            if not version:
                raise ValueError(f"Electron runtime 缺少 {runtime_name} 版本")
            result[notice_name] = version
    return result


def _license_from_tooling(distribution: metadata.Distribution) -> str:
    records = _pip_license_records()
    return records.get(normalize_name(str(distribution.metadata.get("Name") or "")), "")


_PIP_LICENSE_CACHE: dict[str, str] | None = None


def _pip_license_records() -> dict[str, str]:
    global _PIP_LICENSE_CACHE
    if _PIP_LICENSE_CACHE is not None:
        return _PIP_LICENSE_CACHE
    command = shutil.which("pip-licenses")
    args = [command] if command else [sys.executable, "-m", "piplicenses"]
    args.extend(["--format=json", "--with-urls"])
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=30
        )
        raw = json.loads(result.stdout) if result.returncode == 0 else []
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        raw = []
    _PIP_LICENSE_CACHE = {
        normalize_name(str(item.get("Name"))): str(item.get("License") or "").strip()
        for item in raw
        if isinstance(item, dict) and item.get("Name")
    }
    return _PIP_LICENSE_CACHE


def runtime_dependency_versions(project_root: Path = PROJECT_ROOT) -> dict[str, str]:
    """Return the exact, locked Python distribution closure used by the Backend."""

    return {
        name: distribution.version
        for name, distribution in _runtime_dependency_distributions(
            Path(project_root).resolve(),
            distributions=_installed_distributions(),
        ).items()
    }


def runtime_direct_dependency_names(
    project_root: Path = PROJECT_ROOT,
) -> tuple[str, ...]:
    """Return canonical direct runtime distribution names for this platform."""

    requirements = _read_requirements(
        Path(project_root).resolve() / RUNTIME_REQUIREMENTS
    )
    return tuple(
        sorted(
            {
                normalize_name(requirement.name)
                for requirement in requirements
                if requirement.marker is None or requirement.marker.evaluate()
            }
        )
    )


def required_python_component_versions(
    project_root: Path = PROJECT_ROOT,
) -> dict[str, str]:
    """Return the exact Python components that are present in the frozen artifact."""

    project_root = Path(project_root).resolve()
    result = runtime_dependency_versions(project_root)
    installed = _installed_distributions()
    for name in PACKAGED_PYTHON_DISTRIBUTIONS:
        normalized = normalize_name(name)
        distribution = installed.get(normalized)
        if distribution is None:
            raise ValueError(f"构建环境缺少随包组件：{name}")
        result[normalized] = distribution.version
    _validate_packaged_python_versions(result, project_root)
    return result


def _validate_packaged_python_versions(
    components: Mapping[str, str], project_root: Path
) -> None:
    constraints = _read_constraints(project_root / RUNTIME_CONSTRAINTS)
    for name in PACKAGED_PYTHON_DISTRIBUTIONS:
        normalized = normalize_name(name)
        expected = constraints.get(normalized)
        actual = components.get(normalized)
        if expected is None:
            raise ValueError(f"{RUNTIME_CONSTRAINTS} 缺少随包组件：{name}")
        if actual is None or not _versions_equal(str(actual), expected):
            raise ValueError(
                f"随包组件版本不一致：{name} expected={expected}, "
                f"actual={actual or '<missing>'}"
            )


def _runtime_dependency_distributions(
    project_root: Path,
    *,
    distributions: Mapping[str, metadata.Distribution],
) -> dict[str, metadata.Distribution]:
    roots = _read_requirements(project_root / RUNTIME_REQUIREMENTS)
    constraints = _read_constraints(project_root / RUNTIME_CONSTRAINTS)
    if not roots:
        raise ValueError(f"{RUNTIME_REQUIREMENTS} 没有运行时依赖")

    pending = list(roots)
    result: dict[str, metadata.Distribution] = {}
    while pending:
        requirement = pending.pop(0)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        name = normalize_name(requirement.name)
        if name in result:
            actual_version = str(result[name].version or "").strip()
            if requirement.specifier and not requirement.specifier.contains(
                actual_version,
                prereleases=True,
            ):
                raise ValueError(
                    f"运行时传递依赖不满足声明：{requirement.name}{requirement.specifier}, "
                    f"actual={actual_version}"
                )
            continue
        distribution = distributions.get(name)
        if distribution is None:
            raise ValueError(f"构建环境缺少运行时依赖：{requirement.name}")
        actual_version = str(distribution.version or "").strip()
        expected_version = constraints.get(name)
        if expected_version is None:
            raise ValueError(
                f"{RUNTIME_CONSTRAINTS} 缺少运行时依赖：{requirement.name}"
            )
        if not _versions_equal(actual_version, expected_version):
            raise ValueError(
                f"锁定运行时依赖版本不一致：{requirement.name} "
                f"expected={expected_version}, actual={actual_version or '<unknown>'}"
            )
        if requirement.specifier and not requirement.specifier.contains(
            actual_version,
            prereleases=True,
        ):
            raise ValueError(
                f"运行时依赖不满足声明：{requirement.name}{requirement.specifier}, "
                f"actual={actual_version}"
            )
        result[name] = distribution
        for raw_dependency in distribution.requires or ():
            try:
                dependency = Requirement(str(raw_dependency))
            except InvalidRequirement as exc:
                raise ValueError(
                    f"运行时依赖元数据无效：{requirement.name}: {exc}"
                ) from exc
            if dependency.marker is None or dependency.marker.evaluate():
                pending.append(dependency)
    return result


def _read_requirements(path: Path, seen: set[Path] | None = None) -> list[Requirement]:
    seen = seen or set()
    path = path.resolve()
    if path in seen:
        return []
    seen.add(path)
    result: list[Requirement] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            included = line.split(maxsplit=1)[1]
            result.extend(_read_requirements(path.parent / included, seen))
            continue
        if line.startswith("-"):
            continue
        try:
            result.append(Requirement(line))
        except InvalidRequirement as exc:
            raise ValueError(f"运行时依赖声明无效：{line}: {exc}") from exc
    return result


def _read_constraints(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement as exc:
            raise ValueError(f"锁定依赖声明无效：{line}: {exc}") from exc
        exact_versions = [
            item.version
            for item in requirement.specifier
            if item.operator == "==" and "*" not in item.version
        ]
        if len(exact_versions) != 1 or len(tuple(requirement.specifier)) != 1:
            raise ValueError(f"constraint 必须是单一精确版本：{line}")
        result[normalize_name(requirement.name)] = exact_versions[0]
    return result


def _versions_equal(actual: str, expected: str) -> bool:
    try:
        return Version(actual) == Version(expected)
    except InvalidVersion:
        return actual == expected


def audit_runtime_inventory_with_cyclonedx(components: Mapping[str, str]) -> None:
    """Cross-check the locked inventory with the independent cyclonedx-bom CLI."""

    frozen_requirements = "".join(
        f"{normalize_name(name)}=={version}\n"
        for name, version in sorted(components.items())
    )
    command = [
        sys.executable,
        "-m",
        "cyclonedx_py",
        "requirements",
        "-",
        "--sv",
        CYCLONEDX_SPEC_VERSION,
        "--output-reproducible",
        "--of",
        "JSON",
        "--validate",
        "-o",
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            input=frozen_requirements,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"无法运行 cyclonedx-bom 独立审计：{exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ValueError(
            "cyclonedx-bom 独立审计失败" + (f"：{detail}" if detail else "")
        )
    try:
        audit_document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("cyclonedx-bom 独立审计没有返回有效 JSON") from exc
    if (
        audit_document.get("bomFormat") != "CycloneDX"
        or audit_document.get("specVersion") != CYCLONEDX_SPEC_VERSION
    ):
        raise ValueError("cyclonedx-bom 独立审计没有返回 CycloneDX 1.5")
    audit_components = {
        normalize_name(str(item.get("name") or "")): str(item.get("version") or "")
        for item in audit_document.get("components", ())
        if isinstance(item, dict) and item.get("name")
    }
    expected = {
        normalize_name(name): str(version) for name, version in components.items()
    }
    if audit_components != expected:
        missing = sorted(
            f"{name}=={version}"
            for name, version in expected.items()
            if audit_components.get(name) != version
        )
        unexpected = sorted(
            f"{name}=={version}"
            for name, version in audit_components.items()
            if expected.get(name) != version
        )
        details = []
        if missing:
            details.append("缺少/版本不符=" + ", ".join(missing))
        if unexpected:
            details.append("额外/版本不符=" + ", ".join(unexpected))
        raise ValueError("cyclonedx-bom 运行闭包交叉审计不一致：" + "; ".join(details))


def _license_from_metadata(info: metadata.PackageMetadata) -> str:
    license_expression = str(info.get("License-Expression") or "").strip()
    if license_expression:
        return license_expression
    license_text = str(info.get("License") or "").strip()
    if license_text:
        return " ".join(license_text.split())
    classifiers = info.get_all("Classifier") or []
    values = [
        str(item).rsplit("::", 1)[-1].strip()
        for item in classifiers
        if "License ::" in str(item)
    ]
    return ", ".join(values)


def _project_url(info: metadata.PackageMetadata) -> str:
    for value in info.get_all("Project-URL") or []:
        parts = str(value).split(",", 1)
        if len(parts) == 2 and parts[0].strip().casefold() in {
            "homepage",
            "source",
            "repository",
        }:
            return parts[1].strip()
    return str(info.get("Home-page") or "").strip()


def _application_version(project_root: Path) -> str:
    text = (project_root / "src/netconsole/core/version.py").read_text(encoding="utf-8")
    match = re.search(r'APP_VERSION\s*=\s*["\']v?([^"\']+)', text)
    return match.group(1) if match else "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the deterministic NetConsole runtime CycloneDX SBOM"
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / "dist" / "netconsole-runtime.cdx.json",
    )
    args = parser.parse_args()
    write_runtime_sbom(args.output)
    errors = validate_sbom(args.output)
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        return 1
    print(f"[OK] SBOM written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
