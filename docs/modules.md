# Cyberdeck Module API v1

Cyberdeck modules are trusted Python packages that provide native Textual workspaces. They run
inside the Cyberdeck process with the operator's user permissions. Install only code you trust.

Homebrew owns the Cyberdeck runtime. External modules are stored separately under Cyberdeck's
platform data directory, so `brew upgrade cyberdeck` never removes them.

## Create a module

```bash
cyberdeck module init signal-status
cd cyberdeck-module-signal-status
cyberdeck module link .
```

The generated package declares one entry point:

```toml
[project.entry-points."cyberdeck.modules"]
signal-status = "signal_status:create_module"
```

The entry point is a callable that accepts `ModuleContext` and returns a `DeckModule`. Module IDs
are stable lowercase identifiers. A module declares `api_version = 1` and a Cyberdeck version
specifier; incompatible packages are rejected before their workspace is mounted.

`ModuleContext` provides only stable deck services: module-scoped data and configuration paths,
notifications, and clipboard writes. Agent control is intentionally excluded from API v1 while
Cyberdeck's provider-neutral agent contract is being developed.

Module widgets should define scoped `DEFAULT_CSS` on their root widget. External modules may not
replace Cyberdeck's global TCSS or theme structure.

## Install and manage modules

Package names, Git URLs, wheels, local projects, and editable development links are supported:

```bash
cyberdeck module install cyberdeck-module-example
cyberdeck module install git+https://github.com/example/cyberdeck-module-example.git
cyberdeck module install ./dist/cyberdeck_module_example-0.1.0-py3-none-any.whl
cyberdeck module link ./cyberdeck-module-example
cyberdeck module list
cyberdeck module info example
cyberdeck module disable example
cyberdeck module enable example
cyberdeck module update example
cyberdeck module remove example
```

Use `--trust` only in automation where the package source has already been reviewed. Interactive
installs show the source and arbitrary-code warning before proceeding.

The same lifecycle is available inside Cyberdeck with `/modules` and `/module install`, `link`,
`info`, `enable`, `disable`, `update`, and `remove`. New modules mount immediately without stopping
agents. Disabling or removing the active workspace switches to Agent Command first.

Python cannot safely unload arbitrary imported packages. An update is therefore installed and
validated immediately but marked `UPDATE PENDING`; it becomes active on the next launch. If the
replacement fails, Cyberdeck restores the previous environment and reports the rejected update.

## Failure and compatibility behavior

- Package installation occurs in a staging directory and is atomically promoted.
- Cyberdeck-owned dependencies are not duplicated inside module environments.
- Duplicate/reserved IDs, command collisions, and incompatible versions are rejected.
- Import, build, or lifecycle failures affect only the owning module.
- Faulted and disabled modules remain visible in the rail and cannot be activated.
- Agent processes, transcripts, and drafts remain untouched by module lifecycle operations.

Run `cyberdeck module validate SPEC --trust` to install and inspect a package in a temporary
environment without registering it.
