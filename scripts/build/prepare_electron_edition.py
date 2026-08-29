from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from netconsole.core.feature_flags import (
    CUSTOMER_UNLOCK_PASSWORD_MIN_LENGTH,
    default_profile,
    embedded_runtime_dir,
    hash_admin_unlock_password,
    install_embedded_feature_files,
    profiles_dir,
    resolve_customer_unlock_password,
    validate_feature_profile_payload,
    verify_admin_unlock_password,
)

BUILD_EDITIONS = ("full", "customer")
EDITION_ENV = "NETCONSOLE_BUILD_EDITION"


class EditionPreparationError(RuntimeError):
    pass


def prepare_electron_edition(
    backend_root: Path,
    *,
    edition: str,
    customer_password: str | None = None,
) -> dict[str, Any]:
    target = Path(backend_root).resolve()
    normalized_edition = edition.strip().lower()
    if normalized_edition not in BUILD_EDITIONS:
        raise EditionPreparationError(
            f"不支持的 Electron 打包版本：{edition!r}；仅允许 full/customer"
        )
    if not target.is_dir() or not (target / "NetConsoleBackend.exe").is_file():
        raise EditionPreparationError(f"Electron Backend 载荷不存在：{target}")

    password = ""
    if normalized_edition == "customer":
        resolved_password = resolve_customer_unlock_password(customer_password)
        password = resolved_password.value
    if normalized_edition == "customer" and len(password) < CUSTOMER_UNLOCK_PASSWORD_MIN_LENGTH:
        raise EditionPreparationError(
            f"客户版维护密码必须至少 {CUSTOMER_UNLOCK_PASSWORD_MIN_LENGTH} 位"
        )

    profile = normalized_edition
    build_info: dict[str, Any] = {
        "edition": normalized_edition,
        "feature_profile": profile,
        "admin_unlock_enabled": False,
    }
    if normalized_edition == "customer":
        build_info.update(hash_admin_unlock_password(password))

    feature_flags = _load_profile_payload(profile)
    full_flags = _load_profile_payload("full")
    install_embedded_feature_files(
        target,
        build_info=build_info,
        feature_flags=feature_flags,
        session_full_flags=full_flags,
    )

    build_info_path = embedded_runtime_dir(target) / "build_info.json"
    feature_flags_path = embedded_runtime_dir(target) / "feature_flags.json"
    embedded_build_info = _read_json(build_info_path)
    embedded_feature_flags = _read_json(feature_flags_path)
    _validate_embedded_identity(
        embedded_build_info,
        embedded_feature_flags,
        edition=normalized_edition,
        profile=profile,
        customer_password=password,
    )
    if (target / "runtime").exists():
        raise EditionPreparationError(
            "Electron Backend 载荷不得生成顶层 runtime；版本策略必须只存在于内嵌资源"
        )
    result = {
        "edition": normalized_edition,
        "feature_profile": profile,
        "admin_unlock_configured": bool(
            embedded_build_info.get("admin_unlock_enabled")
        ),
        "build_info_path": str(build_info_path),
        "feature_flags_path": str(feature_flags_path),
    }
    print(f"ELECTRON_EDITION={result['edition']}")
    print(f"ELECTRON_FEATURE_PROFILE={result['feature_profile']}")
    print(
        "ELECTRON_ADMIN_UNLOCK_CONFIGURED="
        f"{str(result['admin_unlock_configured']).lower()}"
    )
    return result


def _load_profile_payload(profile: str) -> dict[str, Any]:
    source = profiles_dir() / f"{profile}.json"
    if not source.exists():
        payload = default_profile(profile)
    else:
        payload = _read_json(source)
    payload["profile"] = profile
    errors = validate_feature_profile_payload(payload, profile=profile)
    if errors:
        heading = f"{profile.upper()} PROFILE INVALID"
        detail = "\n".join(f"- {error}" for error in errors)
        raise EditionPreparationError(f"{heading}\n{detail}")
    return payload


def _validate_embedded_identity(
    build_info: dict[str, Any],
    feature_flags: dict[str, Any],
    *,
    edition: str,
    profile: str,
    customer_password: str,
) -> None:
    if build_info.get("edition") != edition:
        raise EditionPreparationError("包内 build_info edition 与目标版本不一致")
    if build_info.get("feature_profile") != profile:
        raise EditionPreparationError("包内 build_info feature_profile 与目标版本不一致")
    if feature_flags.get("profile") != profile:
        raise EditionPreparationError("包内 feature_flags profile 与目标版本不一致")

    serialized = json.dumps(build_info, ensure_ascii=False)
    if customer_password and customer_password in serialized:
        raise EditionPreparationError("客户维护密码不得以明文写入包内身份文件")
    if edition == "customer":
        required = (
            "admin_unlock_enabled",
            "admin_unlock_hash",
            "admin_unlock_salt",
            "admin_unlock_iterations",
        )
        if not all(build_info.get(key) for key in required):
            raise EditionPreparationError("客户版缺少完整的维护密码哈希参数")
        if not verify_admin_unlock_password(build_info, customer_password):
            raise EditionPreparationError("客户版维护密码哈希回读校验失败")
    elif any(
        key in build_info
        for key in (
            "admin_unlock_hash",
            "admin_unlock_salt",
            "admin_unlock_iterations",
        )
    ):
        raise EditionPreparationError("完整版不得携带客户维护密码哈希")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EditionPreparationError(f"无法读取 JSON：{path}") from exc
    if not isinstance(payload, dict):
        raise EditionPreparationError(f"JSON 顶层必须为对象：{path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject Electron edition feature policy")
    parser.add_argument("--backend-root", type=Path, required=True)
    parser.add_argument("--edition", choices=BUILD_EDITIONS)
    args = parser.parse_args()
    edition = args.edition or os.environ.get(EDITION_ENV, "full")
    try:
        prepare_electron_edition(
            args.backend_root,
            edition=edition,
        )
        return 0
    except EditionPreparationError as exc:
        print("ELECTRON EDITION PREPARATION FAILED")
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
