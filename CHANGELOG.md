# Changelog

## 0.1.0 - 2026-09-08

Initial public prototype.

- Resume an existing Codex thread through the Codex CLI.
- Persist watcher state locally.
- Detect usage-limit, network, authentication, and unknown failures.
- Use exponential backoff for temporary transport failures.
- Validate the resumed thread ID from Codex JSONL events.
- Prevent duplicate watchers for the same thread.
- Support queued prompt files and local image paths.
- Avoid interacting with the Codex Desktop composer.
- Add Codex plugin manifest and companion skill documentation.
