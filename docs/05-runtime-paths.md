# Runtime Paths

Development and future portable builds use the same local directory layout under the project root.

Important paths:

- `docs/`: design documents
- `netconsole/`: application source code
- `data/`: runtime data
- `data/sites/demo/db/devices.db`: demo site database
- `data/sites/<site_name>/metrics/`: reserved metrics directory
- `tests/`: pytest tests
- `project/build/`: temporary build files
- `project/dist/`: future portable output
- `project/scripts/`: development and build scripts
- `project/resources/icons/`: icons
- `project/resources/templates/`: import templates
- `project/tools/`: future helper tools

Path construction should go through `PathResolver`.
