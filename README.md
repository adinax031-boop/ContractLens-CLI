# ContractLens

### Ship API changes with clarity.

A local, dependency-free Python CLI for reviewing **OpenAPI 3 JSON** compatibility. Catch removed endpoints, newly required inputs, response shape changes, and enum changes before release. Turn the result into a readable, standalone HTML report.

![CI](https://github.com/adinax031-boop/ContractLens-CLI/actions/workflows/ci.yml/badge.svg)

## Quick start

Python 3.10 or newer. No API keys, hosted service, or runtime dependencies.

```sh
git clone https://github.com/adinax031-boop/ContractLens-CLI.git
cd ContractLens-CLI
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
contractlens before.json after.json
```

The included example produces three breaking findings: a newly required query parameter, a response field that is no longer guaranteed, and an integer response changed to a string.

```sh
contractlens before.json after.json --format html --output report.html --fail-on never
contractlens before.json after.json --format json --output findings.json
python -m contractlens --help
```

Open `report.html` directly in a browser. Reports are portable and contain no remote scripts, fonts, or tracking. The repository includes an example report.

## CI behavior

| Exit | Meaning |
| --- | --- |
| 0 | No findings at the selected failure threshold |
| 1 | Findings reached the failure threshold |
| 2 | Invalid/unsupported input or file error |

Default: fail on `breaking`. Use `--fail-on review` to fail on both breaking and uncertain changes. Use `--fail-on never` to generate reports without a compatibility failure; input errors still exit 2.

```yaml
- run: python -m pip install .
- run: contractlens baseline.json candidate.json --fail-on review
```

The supplied GitHub Actions workflow tests Python 3.10–3.14, installs the package, exercises the CLI and uploads example report artifacts. It tests this tool; configure the above comparison separately against your own API contracts.

## Supported checks

| Area | Checks |
| --- | --- |
| Routes | Removed paths and HTTP operations |
| Inputs | Inherited/overridden parameters, required parameters and bodies, removed request media |
| Schemas | Types, required fields, nested properties, array items, enum direction, 3.0 nullable |
| Responses | Removed statuses and properties, new statuses for review, new response media |
| Review | Changed constraints/combinators, serialization, headers, security, callbacks and servers |
| References | Local JSON pointers, including escaped pointer tokens |

Request and response changes are directional: a narrower input enum breaks existing callers; a broader output enum may break consumers. New optional response properties are accepted. Changed constraints whose compatibility cannot be established become `review` findings.

## Scope and limits

This is a structural review tool, **not a complete OpenAPI validator or proof of compatibility**. Use an OpenAPI validator first. Input must be JSON; YAML and external references are not supported. Only the documented subset is checked. Unchanged constraints containing nested references, webhooks, links, newly added operations, path-level servers, response encoding, and vendor extension semantics are not exhaustively compared. Boolean schemas are not supported. Recursive schemas fail with exit 2 rather than being silently accepted; nesting is limited to 64 levels. Composition changes are flagged for manual review rather than solved. Header schemas are flagged as a group when their definitions change. Global security scheme changes are flagged conservatively, including unused schemes.

Changes to descriptions, examples and titles are ignored. The tool does not send network requests or execute contract content. HTML values are escaped. Large or hostile inputs should be processed with normal CI resource limits. Reports include contract field names and descriptions of changes: treat reports according to your API's confidentiality.

## Python API

```python
from contractlens import compare, render_html
findings = compare(old_openapi_dict, new_openapi_dict)
for finding in findings:
    print(finding.severity, finding.location, finding.message)
html = render_html(findings)
```

`compare` returns sorted, deduplicated immutable `Finding` objects. Unsupported documents raise `ContractError`; malformed structures can raise standard Python validation errors. The CLI converts these to exit 2.

## Development

```sh
python -m unittest discover -v
python -m compileall -q contractlens.py test_contractlens.py
python -m pip install .
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [CHANGELOG.md](CHANGELOG.md). MIT licensed. Package metadata is provided for local installation; no PyPI publication is claimed.
