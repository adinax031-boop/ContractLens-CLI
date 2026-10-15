# Contributing

Open an issue describing a concrete contract change and the expected client impact. For a pull request, include small before/after JSON fixtures in a regression test. Avoid real credentials or private API specifications.

Use Python 3.10-compatible standard-library code. Run `python -m unittest discover -v` from the repository root. Keep output deterministic, escape user content in HTML, and preserve the documented exit code contract. A rule should only label a change breaking when its direction is established; otherwise use review and explain the uncertainty.

Changes to supported scope must update README.md and CHANGELOG.md. CI runs the supported Python matrix. Maintainers review contributions before merge.
