from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .api import create_app
from .catalog import Catalog
from .config import Settings
from .ingest import ImportService
from .models import ImportRequest


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="race-review")
    subcommands = root.add_subparsers(dest="command", required=True)
    serve = subcommands.add_parser("serve", help="Start the local API and built frontend")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    import_parser = subcommands.add_parser("import", help="Import explicitly ordered MP4 chapters")
    import_parser.add_argument("chapters", nargs="+")
    import_parser.add_argument("--name")
    import_parser.add_argument("--media-root", action="append", default=[])
    import_parser.add_argument("--skip-proxy", action="store_true")
    return root


def main() -> None:
    arguments = parser().parse_args()
    if arguments.command == "serve":
        import uvicorn

        uvicorn.run(create_app(), host=arguments.host, port=arguments.port)
        return

    if arguments.media_root:
        os.environ["RACE_REVIEW_MEDIA_ROOTS"] = os.pathsep.join(
            str(Path(item).expanduser().resolve()) for item in arguments.media_root
        )
    settings = Settings.from_env()
    settings.ensure_directories()
    catalog = Catalog(settings.database_path)
    service = ImportService(settings, catalog)
    request = ImportRequest(
        chapters=arguments.chapters,
        name=arguments.name,
        generate_proxy=not arguments.skip_proxy,
    )
    manifest = service.prepare(request)
    print(json.dumps({"session_id": manifest.session_id, "status": "processing"}))
    result = service.process(manifest.session_id, request)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
