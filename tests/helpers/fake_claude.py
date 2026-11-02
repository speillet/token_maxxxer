"""Offline CLI fixture. Never imports a Claude SDK or calls a network service."""

import json
import os
import signal
import sys
import time
from pathlib import Path

case = os.environ.get("FIXTURE_CASE", "success")
with Path("calls.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\n")

if sys.argv[1:] == ["--version"]:
    print("2.1.998 (fixture)" if case == "version_change" else "2.1.999 (fixture)")
elif sys.argv[1:] == ["auth", "status"]:
    print(
        json.dumps(
            {
                "loggedIn": case != "logged_out",
                "authMethod": "api_key" if case == "api_auth" else "claude.ai",
                "email": "private@example.invalid",
                "token": "private-fixture-token",
            }
        )
    )
elif "-p" in sys.argv:
    prompt = sys.stdin.read()
    if case == "timeout":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(60)
    elif case == "crash":
        os.kill(os.getpid(), signal.SIGKILL)
    elif case == "malformed":
        print('{"type":"result"')
    elif case == "invalid_encoding":
        sys.stdout.buffer.write(b"\xff")
    elif case == "echo":
        print(
            json.dumps(
                {"type": "result", "subtype": "success", "is_error": False, "result": prompt}
            )
        )
    else:
        fixture = Path(__file__).resolve().parents[1] / "fixtures/claude" / f"{case}.json"
        sys.stdout.write(fixture.read_text(encoding="utf-8"))
        sys.exit(0 if case in ("success", "internal_error") else 1)
else:
    raise SystemExit(99)
