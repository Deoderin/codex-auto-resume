# Architecture

## Overview

Codex Auto Resume consists of two conceptual layers:

1. a Codex plugin/skill surface that explains and operates the feature;
2. a local Python companion that can remain alive while Codex itself is unavailable because of a usage limit.

The local companion is the important part. A model-driven skill cannot reliably wake itself after the model is blocked by quota, so retry scheduling must happen outside the interrupted Codex turn.

## Lifecycle

### 1. Configuration

The user provides:

- an existing Codex thread/session ID;
- an optional working directory;
- an initial continuation prompt or prompt file;
- optional local image paths;
- a retry interval.

The companion resolves and validates local paths before it begins.

### 2. State persistence

Configuration is serialized to a small JSON state file in the platform-specific local state directory.

The session ID is not used directly as a file name. A SHA-256 prefix is used to derive the state and lock file names.

### 3. Single-watcher lock

A lock file is created atomically with `O_CREAT | O_EXCL`. If the lock already exists, the process stops rather than allowing two independent loops to submit turns to the same thread.

### 4. Codex invocation

The companion invokes:

```text
codex exec --json [--cd <project>] resume <thread-id> [--image <path> ...] -
```

The prompt is written through standard input. This avoids shell quoting issues and command-line length problems for large prompts.

### 5. Event validation

The companion parses JSONL events from **stdout only**.

Important events include:

- `thread.started`
- `turn.started`
- `turn.completed`

If `thread.started.thread_id` differs from the requested thread, the watcher performs a safety stop.

### 6. Initial payload protection

If the first queued payload includes images or a large task prompt, it should not be blindly replayed after Codex has already begun the turn.

Once `turn.started` is observed, `initial_submitted` is persisted. Future retries then use the continuation prompt rather than replaying the original payload.

### 7. Error classification

CLI output is classified into four broad groups:

- usage/rate limit;
- authentication;
- network/transport;
- unexpected/other.

Usage-limit failures wait and retry.

Network failures use exponential backoff.

Authentication and unknown failures stop and preserve state for manual inspection.

## Why the Desktop composer is not automated

UI automation would make the tool brittle and potentially destructive. A Desktop draft may contain text, pasted screenshots, files, or other unsent context. Clicking or simulating keyboard input could overwrite, duplicate, or accidentally submit that draft.

The companion therefore treats the Desktop composer as user-owned state and never attempts to interact with it.

## Why this does not bypass limits

The loop makes normal Codex CLI requests. When the service rejects a request because the account is still limited, the companion waits. Work resumes only after the service itself accepts the request again.

No account setting, token bucket, clock, header, credential, or limit value is modified.

## Failure philosophy

The project favors false negatives over dangerous false positives.

If the tool cannot prove that it resumed the intended thread, or cannot classify a failure safely, it stops. Automatic recovery is useful only while the recovery target remains unambiguous.
