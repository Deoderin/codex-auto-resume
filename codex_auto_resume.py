#!/usr/bin/env python3
"""
Codex Auto Resume
- Waits out ChatGPT/Codex usage-limit errors.
- Resumes an EXISTING Codex thread only.
- Can queue text + local image paths.
- Verifies that Codex actually resumed the requested thread.
- Persists state locally so the watcher can be restarted.

Recommended Codex CLI: current @openai/codex.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable


RATE_LIMIT_MARKERS = (
    "usage limit",
    "rate limit",
    "rate_limit",
    "too many requests",
    "5-hour",
    "5 hour",
    "five-hour",
    "five hour",
    "try again later",
    "try again at",
    "resets at",
    "reset at",
    "quota",
    "usage cap",
)

AUTH_MARKERS = (
    "not logged in",
    "authentication",
    "unauthorized",
    "forbidden",
    "invalid api key",
    "login required",
)

NETWORK_MARKERS = (
    "network error",
    "connection reset",
    "connection refused",
    "timed out",
    "timeout",
    "temporary failure",
    "dns",
    "stream disconnected",
    "transport error",
)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    print(f"[{now()}] {message}", flush=True)


def app_state_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    p = base / "codex-auto-resume"
    p.mkdir(parents=True, exist_ok=True)
    return p


def session_key(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


@dataclass
class WatchState:
    session_id: str
    cwd: str | None
    initial_prompt: str
    continuation_prompt: str
    images: list[str] = field(default_factory=list)
    initial_submitted: bool = False
    attempts: int = 0


class SessionLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def __enter__(self):
        try:
            self.fd = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            os.write(self.fd, str(os.getpid()).encode())
            return self
        except FileExistsError:
            raise SystemExit(
                f"Watcher for this session already appears to be running.\n"
                f"Lock: {self.path}\n"
                f"If it crashed previously, delete that lock file."
            )

    def __exit__(self, exc_type, exc, tb):
        if self.fd is not None:
            os.close(self.fd)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def save_state(path: Path, state: WatchState) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(asdict(state), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)


def load_state(path: Path) -> WatchState:
    data = json.loads(path.read_text(encoding="utf-8"))
    return WatchState(**data)


def classify_error(text: str) -> str:
    low = text.lower()
    if any(x in low for x in RATE_LIMIT_MARKERS):
        return "rate_limit"
    if any(x in low for x in AUTH_MARKERS):
        return "auth"
    if any(x in low for x in NETWORK_MARKERS):
        return "network"
    return "other"


def parse_stdout_events(stdout: str) -> tuple[str | None, bool, bool]:
    """
    Parse ONLY stdout JSONL.
    Returns: (reported_thread_id, turn_started, turn_completed)

    We deliberately do not trust JSON-looking stderr for thread identity.
    """
    reported_thread_id = None
    turn_started = False
    turn_completed = False

    for raw in stdout.splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type")

        if event_type == "thread.started":
            tid = event.get("thread_id")
            if isinstance(tid, str):
                reported_thread_id = tid
        elif event_type == "turn.started":
            turn_started = True
        elif event_type == "turn.completed":
            turn_completed = True

    return reported_thread_id, turn_started, turn_completed


def validate_paths(cwd: str | None, images: Iterable[str]) -> tuple[str | None, list[str]]:
    resolved_cwd = None
    if cwd:
        p = Path(cwd).expanduser().resolve()
        if not p.is_dir():
            raise SystemExit(f"--cwd is not a directory: {p}")
        resolved_cwd = str(p)

    resolved_images: list[str] = []
    for image in images:
        p = Path(image).expanduser().resolve()
        if not p.is_file():
            raise SystemExit(f"Image not found: {p}")
        resolved_images.append(str(p))

    return resolved_cwd, resolved_images


def find_codex() -> str:
    exe = shutil.which("codex")
    if not exe:
        raise SystemExit(
            "Could not find 'codex' in PATH.\n"
            "Install/update the Codex CLI first and make sure `codex --version` works."
        )
    return exe


def run_codex(
    codex_exe: str,
    state: WatchState,
    prompt: str,
    images: list[str],
) -> tuple[int, str, str]:
    # Shared exec flags come before `resume`.
    command = [codex_exe, "exec", "--json"]

    if state.cwd:
        command += ["--cd", state.cwd]

    command += ["resume", state.session_id]

    for image in images:
        command += ["--image", image]

    # Explicit "-" makes stdin the prompt, avoiding shell quoting/length problems.
    command += ["-"]

    env = os.environ.copy()
    # Avoid debug tracing contaminating stderr with JSON-looking tool output.
    env.pop("RUST_LOG", None)

    proc = subprocess.run(
        command,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    return proc.returncode, proc.stdout or "", proc.stderr or ""


def jittered(seconds: float, pct: float = 0.08) -> float:
    spread = seconds * pct
    return max(1.0, seconds + random.uniform(-spread, spread))


def watch(
    state: WatchState,
    state_path: Path,
    retry_seconds: int,
    max_network_backoff: int,
) -> int:
    codex_exe = find_codex()
    network_failures = 0

    while True:
        state.attempts += 1
        save_state(state_path, state)

        first_payload = not state.initial_submitted
        prompt = state.initial_prompt if first_payload else state.continuation_prompt
        images = state.images if first_payload else []

        mode = "queued payload" if first_payload else "continuation"
        log(f"Attempt #{state.attempts}: sending {mode} to thread {state.session_id}")

        code, stdout, stderr = run_codex(
            codex_exe=codex_exe,
            state=state,
            prompt=prompt,
            images=images,
        )

        combined = stdout + "\n" + stderr
        reported_thread, turn_started, turn_completed = parse_stdout_events(stdout)

        # Critical safety check: current Codex versions have had cases where a bad
        # resume id silently creates a new thread. Never continue in that case.
        if reported_thread and reported_thread != state.session_id:
            log("SAFETY STOP: Codex did not resume the requested thread.")
            log(f"Expected: {state.session_id}")
            log(f"Got:      {reported_thread}")
            log("Nothing further will be sent.")
            return 20

        # Once a turn has actually started, never resend the original images/task
        # after a later quota interruption. Subsequent wake-ups use "continue".
        if first_payload and turn_started:
            state.initial_submitted = True
            save_state(state_path, state)

        if code == 0 and turn_completed:
            log("Turn completed successfully.")
            try:
                state_path.unlink()
            except FileNotFoundError:
                pass
            return 0

        kind = classify_error(combined)

        if kind == "rate_limit":
            # If the request reached turn.started, we will continue rather than
            # duplicate the original queued task/images on the next window.
            wait = jittered(retry_seconds)
            log(
                f"Usage limit is still active. "
                f"Retrying in about {int(wait)} seconds."
            )
            time.sleep(wait)
            network_failures = 0
            continue

        if kind == "network":
            network_failures += 1
            backoff = min(
                max_network_backoff,
                max(10, retry_seconds // 2) * (2 ** min(network_failures - 1, 5)),
            )
            wait = jittered(backoff)
            log(f"Temporary network/transport failure. Retry in about {int(wait)} seconds.")
            time.sleep(wait)
            continue

        if kind == "auth":
            log("Authentication problem. Run `codex` interactively and sign in again.")
            print(stderr.strip() or stdout.strip())
            return 30

        log(f"Codex exited with code {code} for a non-rate-limit reason.")
        print((stderr.strip() or stdout.strip())[-5000:])
        log(f"State kept at: {state_path}")
        return code if code != 0 else 40


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).expanduser().read_text(encoding="utf-8")
    return args.prompt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely resume a Codex thread after its usage limit resets."
    )
    parser.add_argument("--session", help="Existing Codex thread/session id")
    parser.add_argument("--cwd", help="Project working directory")
    parser.add_argument(
        "--prompt",
        default="Continue working from where you stopped. Do not repeat completed work.",
        help="Queued first prompt",
    )
    parser.add_argument("--prompt-file", help="Read queued first prompt from UTF-8 file")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        help="Local image path. Repeat for multiple images.",
    )
    parser.add_argument(
        "--continue-prompt",
        default=(
            "Continue the current task from the exact point where the previous turn "
            "was interrupted. Review the existing thread and repository state first. "
            "Do not repeat work that is already complete."
        ),
    )
    parser.add_argument(
        "--retry",
        type=int,
        default=60,
        help="Seconds between quota checks (default: 60)",
    )
    parser.add_argument(
        "--max-network-backoff",
        type=int,
        default=300,
        help="Maximum network retry backoff in seconds (default: 300)",
    )
    parser.add_argument(
        "--resume-state",
        action="store_true",
        help="Reload this session's persisted watcher state",
    )

    args = parser.parse_args()

    if args.retry < 30:
        raise SystemExit("--retry must be at least 30 seconds.")

    state_dir = app_state_dir()

    if args.resume_state:
        if not args.session:
            raise SystemExit("--resume-state requires --session.")
        state_path = state_dir / f"{session_key(args.session)}.json"
        if not state_path.exists():
            raise SystemExit(f"No saved state found for {args.session}")
        state = load_state(state_path)
    else:
        if not args.session:
            raise SystemExit("--session is required.")
        cwd, images = validate_paths(args.cwd, args.image)
        prompt = read_prompt(args)

        if not prompt.strip():
            raise SystemExit("Prompt is empty.")

        state = WatchState(
            session_id=args.session,
            cwd=cwd,
            initial_prompt=prompt,
            continuation_prompt=args.continue_prompt,
            images=images,
        )
        state_path = state_dir / f"{session_key(args.session)}.json"
        save_state(state_path, state)

    lock_path = state_dir / f"{session_key(state.session_id)}.lock"

    log(f"State file: {state_path}")
    log("The Codex Desktop composer is not read, clicked, typed into, or cleared by this script.")

    try:
        with SessionLock(lock_path):
            return watch(
                state=state,
                state_path=state_path,
                retry_seconds=args.retry,
                max_network_backoff=args.max_network_backoff,
            )
    except KeyboardInterrupt:
        log("Stopped by user. Saved state was kept.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
