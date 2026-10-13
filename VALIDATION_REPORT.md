# Reliability validation: October 13, 2026

The original October 11 ZIP checksums were verified before staging. Its executable
files and original tests were preserved. Four read-only compatibility tests for the
actual repository were added at tests/test_release_repository.py.

## Repeated local results

- 31 original Python tests passed.
- Six service-worker checks passed.
- Python compilation and JavaScript syntax checks passed.
- Six workflow YAML files parsed successfully.
- Installed local versions matched beautifulsoup4 4.14.3 and jsonschema 4.26.0.

The added repository compatibility tests cover required assets, legacy intelligence
exports, the real archive catalog, and compiling the real template in a temporary
directory. Their results must be established by GitHub PR CI, not inferred from
local fixture tests. The local container could not resolve GitHub for a clone;
read-only connector access to the repository succeeded.

## Evidence limits

Local research, speech and public-download behavior were simulated. No local test
establishes real API authorization, model accuracy, production MP3 duration, live
Pages delivery, iPhone playback, podcast subscription refresh or notification
receipt. A green PR test run is also not a production deployment.

The full cutover and acceptance gates are in DEPLOYMENT_STATUS.md and RELIABILITY.md.
