from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FluentRuntime:
    available: bool
    error: str = ""


try:
    from qfluentwidgets import (  # type: ignore
        Action,
        FluentIcon,
        NavigationInterface,
        NavigationItemPosition,
        CommandBar,
        PushButton,
        PrimaryPushButton,
        SplitFluentWindow,
        InfoBar,
        InfoBarPosition,
        SettingCard,
        SettingCardGroup,
        Theme,
        TransparentToolButton,
        qconfig,
        setTheme,
        setThemeColor,
    )
    FIF = FluentIcon

    FLUENT_RUNTIME = FluentRuntime(True)
except Exception as exc:  # pragma: no cover - fallback path depends on runtime packaging
    Action = None
    CommandBar = None
    FIF = None
    FluentIcon = None
    InfoBar = None
    InfoBarPosition = None
    NavigationInterface = None
    NavigationItemPosition = None
    PrimaryPushButton = None
    PushButton = None
    SettingCard = None
    SettingCardGroup = None
    SplitFluentWindow = None
    Theme = None
    TransparentToolButton = None
    qconfig = None
    setTheme = None
    setThemeColor = None
    FLUENT_RUNTIME = FluentRuntime(False, exc.__class__.__name__)


def fluent_available() -> bool:
    return FLUENT_RUNTIME.available


def fluent_icon(name: str) -> Any:
    if FIF is None:
        return None
    return getattr(FIF, name, getattr(FIF, "APPLICATION", None))


def apply_fluent_theme(theme: str) -> None:
    if not FLUENT_RUNTIME.available or Theme is None or setTheme is None or setThemeColor is None:
        return
    fluent_theme = Theme.DARK if theme == "dark" else Theme.LIGHT
    setTheme(fluent_theme)
    setThemeColor("#2f6fed")
