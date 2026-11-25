"""One network service per supervised process, with pipe-owned lifetime."""

from __future__ import annotations

import json
import logging
import os
import ssl
import sys
from pathlib import Path
from threading import Event, Thread

from netconsole.services.local_network_services.manager import ServiceConfig
from netconsole.services.local_network_services.protocols import create_server


def main() -> int:
    server = None
    worker = None
    stopping = Event()
    try:
        bootstrap = json.loads(sys.stdin.buffer.readline(16385))
        kind = bootstrap["kind"]
        if kind not in {"http", "https", "tftp", "ftp", "syslog"}:
            raise ValueError("unsupported_service")
        config = ServiceConfig.model_validate(bootstrap["config"])
        root = Path(bootstrap["root"]) if bootstrap["root"] else None
        logger = logging.Logger(f"network-service.{kind}", config.log_level)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)
        certificate = bootstrap.get("certificate")
        if kind == "ftp":
            from netconsole.services.local_network_services.ftp import LocalFtpServer

            server = LocalFtpServer(config, root, logger, stopping, certificate, password=bootstrap["password"])
        else:
            context = None
            if kind == "https":
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.load_cert_chain(*certificate)
            server = create_server(kind, config, root, logger, stopping, ssl_context=context)
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        worker.start()
        print(json.dumps({"ready": True, "pid": os.getpid()}), flush=True)

        def watch_control():
            sys.stdin.buffer.readline(64)
            stopping.set()

        Thread(target=watch_control, daemon=True).start()
        while worker.is_alive() and not stopping.wait(0.1):
            pass
        return 0 if stopping.is_set() else 1
    except Exception as exc:
        try:
            print(json.dumps({"ready": False, "errno": getattr(exc, "errno", None), "error": type(exc).__name__}), flush=True)
        except OSError:
            pass
        return 1
    finally:
        if server is not None:
            if worker is not None and worker.is_alive():
                server.shutdown()
            server.server_close()
            if worker is not None:
                worker.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
