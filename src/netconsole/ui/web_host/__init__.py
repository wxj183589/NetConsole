__all__ = ["BrowserHostWidget", "WebConsoleHost"]


def __getattr__(name: str):
    if name in __all__:
        from netconsole.ui.web_host.browser_host_widget import BrowserHostWidget, WebConsoleHost

        return {"BrowserHostWidget": BrowserHostWidget, "WebConsoleHost": WebConsoleHost}[name]
    raise AttributeError(name)
