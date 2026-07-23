from __future__ import annotations


APP_NAME = "NetConsole"
APP_VERSION = "v1.4.2"
APP_VERSION_DISPLAY = APP_VERSION
APP_BYLINE = "by WXJ"
APP_TITLE_DISPLAY = f"{APP_NAME} {APP_VERSION_DISPLAY} {APP_BYLINE}"
BUILD_TIME = "2026-07-22 06:01:24"
GIT_COMMIT = "0288ba1d"
APP_AUTHOR = "梦游"
REPOSITORY_PUSH_URLS = (
    "git@github.com:wxj183589/NetConsole.git",
    "ssh://git@nas.love-ok.com:3022/mengyou/NetConsole.git",
)
REPOSITORY_WEB_URLS = (
    "https://github.com/wxj183589/NetConsole.git",
    "https://nas.love-ok.com:3021/mengyou/NetConsole.git",
)
# 兼容旧调用；用户界面只能使用可由浏览器打开的 HTTPS 地址。
REPOSITORY_URLS = REPOSITORY_WEB_URLS
