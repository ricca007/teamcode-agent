# MVP Interface Registry

C uses the existing async SQLAlchemy session and shared InterfaceContract model. C metadata stores version snapshots and semantic notes. A/B and the shared entry point are unchanged.

Watcher → debounced incremental AST scan → database commit → cache update → `interface.updated`. Unchanged files are skipped. Signatures preserve Python calling conventions; hashes include async status, decorators and statically resolvable imported-call dependencies. Deleted interfaces retain history. Markdown includes IDs, dependencies, versions and available commit references.

The watcher observes the shared repository. Private Agent output enters the registry after review/merge. Authenticated refresh cannot override the configured project root with an arbitrary directory.

REST, CLI and stdio MCP expose the same authenticated data. Optional semantic notes require a configured compatible model endpoint. `TEAMCODE_LLM_AUTO=1` enables automatic generation; revision metadata flags stale notes. Missing configuration never produces fabricated model output.

See [the interface contract](interface_contract.md) for routes and data boundaries. Coursework reports and generated evaluation results are maintained outside the versioned source files.
