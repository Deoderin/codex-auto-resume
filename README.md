# Codex Auto Resume

A small, unofficial companion for Codex that waits through usage-limit windows and resumes an existing Codex thread when capacity becomes available again.

> **Status:** experimental / prototype. This project is not affiliated with or endorsed by OpenAI.

## Why this exists

Long-running Codex tasks can be interrupted when an account reaches a usage limit. Codex Auto Resume keeps a lightweight local watcher running next to Codex and retries the existing thread instead of requiring you to come back and resume it manually.

It does **not** bypass, evade, increase, or modify any OpenAI limit. It simply waits until Codex accepts requests again.

## How it works

```text
Existing Codex thread
        |
        | codex exec resume <thread-id>
        v
+-----------------------+
| Codex Auto Resume     |
+-----------------------+
        |
        +-- success --------------------> done
        |
        +-- usage limit ----------------> wait -> retry
        |
        +-- temporary network failure --> backoff -> retry
        |
        +-- auth / unexpected error ----> stop safely
```

The watcher launches the official Codex CLI in JSON mode and resumes a specific thread. It inspects the CLI event stream to confirm that Codex actually resumed the requested thread. If the returned thread ID does not match, the watcher stops instead of continuing in the wrong conversation.

State is persisted locally, so a stopped watcher can be restarted without reconstructing its configuration.

## Safety model

Codex Auto Resume is intentionally conservative:

- It only resumes an **existing** Codex thread.
- It never clicks, types into, reads, or clears the Codex Desktop composer.
- Draft text and attachments that exist only in the Desktop composer are not read by this tool.
- It verifies the thread ID reported by Codex before continuing.
- It uses a per-thread lock to avoid accidentally running two watchers for the same thread.
- It distinguishes usage-limit, network, authentication, and unexpected failures.
- It removes `RUST_LOG` from the child process to reduce noisy/debug output affecting event parsing.
- It does not repeatedly send an original queued payload after the turn has already started.

## Requirements

- Python 3.10+
- A current Codex CLI installation
- `codex` available in `PATH`
- An authenticated Codex CLI session

Verify the CLI first:

```bash
codex --version
```

## Quick start

Clone the repository:

```bash
git clone https://github.com/Deoderin/codex-auto-resume.git
cd codex-auto-resume
```

Resume an existing thread:

```bash
python codex_auto_resume.py \
  --session "YOUR_THREAD_ID" \
  --cwd "/path/to/your/project"
```

On Windows PowerShell:

```powershell
python .\codex_auto_resume.py `
  --session "YOUR_THREAD_ID" `
  --cwd "D:\Projects\MyProject"
```

The default continuation prompt is:

```text
Continue working from where you stopped. Do not repeat completed work.
```

## Queue a prompt

You can provide the first prompt directly:

```bash
python codex_auto_resume.py \
  --session "YOUR_THREAD_ID" \
  --cwd "/path/to/project" \
  --prompt "Continue implementing the current task."
```

For long prompts, use a UTF-8 text file:

```bash
python codex_auto_resume.py \
  --session "YOUR_THREAD_ID" \
  --cwd "/path/to/project" \
  --prompt-file "task.txt"
```

## Queue images

Local image files can be supplied to the resumed turn:

```bash
python codex_auto_resume.py \
  --session "YOUR_THREAD_ID" \
  --cwd "/path/to/project" \
  --prompt-file "task.txt" \
  --image "reference-1.png" \
  --image "reference-2.png"
```

Images attached only inside the Codex Desktop composer are intentionally outside this tool's control. If an image must be part of an automated retry, keep the original file on disk and pass it with `--image`.

## Retry behavior

By default, usage-limit checks are retried roughly once per minute with a small amount of jitter:

```bash
python codex_auto_resume.py \
  --session "YOUR_THREAD_ID" \
  --retry 60
```

Temporary network errors use exponential backoff, capped by `--max-network-backoff`.

The minimum quota retry interval is 30 seconds to avoid aggressive polling.

## Persistent state

Watcher state is stored outside the repository:

- Windows: `%LOCALAPPDATA%\codex-auto-resume\`
- macOS: `~/Library/Application Support/codex-auto-resume/`
- Linux: `$XDG_STATE_HOME/codex-auto-resume/` or `~/.local/state/codex-auto-resume/`

If the watcher is stopped with `Ctrl+C`, the state file is intentionally kept.

Restart it with:

```bash
python codex_auto_resume.py \
  --session "YOUR_THREAD_ID" \
  --resume-state
```

## Codex plugin manifest

This repository also contains a Codex plugin manifest under:

```text
.codex-plugin/plugin.json
```

and a companion skill under:

```text
skills/auto-resume/SKILL.md
```

The plugin surface documents and helps operate the local watcher. The actual waiting process must live outside the model turn, because a Codex skill cannot execute after the model itself has become unavailable due to a usage limit.

That separation is deliberate:

```text
Codex plugin / skill
        |
        | starts or explains
        v
Local companion process
        |
        | survives quota interruption
        v
Codex CLI resume
```

## Current limitations

Version 0.1 intentionally does **not**:

- bypass OpenAI usage limits;
- modify Codex account settings;
- inspect or manipulate the Codex Desktop UI;
- scrape unsent Desktop drafts or clipboard-only attachments;
- guarantee an exact wake-up timestamp from a structured `resets_at` event;
- automatically discover the currently focused Desktop thread;
- run as an OS service by default.

These are candidates for future versions where they can be implemented reliably without coupling the project to unstable Desktop internals.

## Design principles

1. **Never bypass the quota.** Wait for legitimate capacity to return.
2. **Resume, do not recreate.** Preserve the original Codex thread whenever possible.
3. **Fail closed.** A thread mismatch or unknown failure stops automation.
4. **Do not touch the Desktop composer.** UI drafts belong to the user.
5. **Persist minimal state.** Store only what is required to restart the watcher.
6. **Prefer official interfaces.** Use the Codex CLI rather than UI automation.

For a deeper explanation, see [`docs/architecture.md`](docs/architecture.md).

## CLI options

```text
--session                 Existing Codex thread/session ID
--cwd                     Project working directory
--prompt                  First queued prompt
--prompt-file             Read first queued prompt from a UTF-8 file
--image                   Local image path; may be repeated
--continue-prompt         Prompt used after an already-started turn is interrupted
--retry                   Seconds between quota retries (minimum 30)
--max-network-backoff     Maximum network retry backoff
--resume-state            Reload persisted state for the given session
```

## Security and privacy

The watcher runs locally and invokes the `codex` executable already installed on your machine. It does not contain an OpenAI API key and does not send telemetry of its own.

Queued prompt text and image paths may be written to the local state file so the watcher can survive a restart. Do not queue secrets you would not want stored in that local state directory.

## Roadmap

Potential next steps:

- structured parsing of exact quota reset timestamps when exposed reliably by the CLI;
- safe automatic current-thread discovery;
- Windows Task Scheduler / systemd / launchd helpers;
- a small tray UI;
- improved event-level detection of “failed before start” versus “interrupted mid-turn”;
- optional exact-turn replay when the failed turn can be captured through a stable official interface.

## Disclaimer

Codex Auto Resume is an independent community project. “Codex” and “OpenAI” are trademarks of their respective owners. OpenAI may change Codex CLI behavior, event schemas, plugin formats, or usage-limit behavior at any time.

## License

MIT. See [`LICENSE`](LICENSE).
