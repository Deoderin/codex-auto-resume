---
name: auto-resume
description: Configure or explain the Codex Auto Resume local companion for an existing Codex thread.
---

# Codex Auto Resume

Use this skill when the user wants to configure, start, restart, inspect, or understand the Codex Auto Resume companion included with this plugin.

## Core rule

Never claim that this plugin bypasses an OpenAI or Codex usage limit. It only retries after the service accepts requests again.

## Safety rules

- Do not automate or manipulate the Codex Desktop composer.
- Do not claim access to unsent Desktop drafts or attachments.
- Only resume an existing thread ID supplied or reliably resolved through an official interface.
- Prefer the included `codex_auto_resume.py` companion over UI automation.
- If the CLI reports a different resumed thread ID than requested, stop rather than continuing automatically.
- Do not lower the retry interval below 30 seconds.

## Starting the watcher

From the plugin/repository root, run:

```bash
python codex_auto_resume.py --session "<thread-id>" --cwd "<project-path>"
```

For a queued prompt stored in a file:

```bash
python codex_auto_resume.py \
  --session "<thread-id>" \
  --cwd "<project-path>" \
  --prompt-file "<prompt-file>"
```

Images that must be submitted automatically must exist as local files:

```bash
python codex_auto_resume.py \
  --session "<thread-id>" \
  --cwd "<project-path>" \
  --prompt-file "<prompt-file>" \
  --image "<image-path>"
```

## Restarting saved state

```bash
python codex_auto_resume.py --session "<thread-id>" --resume-state
```

## Explaining behavior

When explaining the implementation, emphasize:

1. The companion process runs outside the interrupted model turn.
2. It invokes `codex exec --json ... resume` for a specific existing thread.
3. It validates `thread.started` before continuing.
4. It persists minimal local state.
5. It waits on usage-limit failures and backs off on temporary network failures.
6. It never touches the Codex Desktop composer.

For more detail, read `README.md` and `docs/architecture.md` from the plugin root.
