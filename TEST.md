# MOESkills CLI Test Notes

## Scope

This file records the minimum verification path for the local `moeskills` CLI.

## Commands

Install the package in editable mode:

```bash
./.venv/bin/pip install -e .
```

Run the connector CLI test suite:

```bash
./.venv/bin/pytest -q tests/test_connector_cli.py
```

Check the installed console script:

```bash
./.venv/bin/moeskills --version
./.venv/bin/moeskills runs wait --help
./.venv/bin/moeskills shell --help
```
