"""Run regression tests against checksum-verified AstrBot v4.29.4 source."""

import hashlib
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

FILES = {
    "ASTRBOT_SESSION_WAITER_SOURCE": (
        "astrbot/core/utils/session_waiter.py",
        "f196dd00a241ed3a509f9b40da1b9d53eaab313c",
    ),
    "ASTRBOT_PROCESS_STAGE_SOURCE": (
        "astrbot/core/pipeline/process_stage/stage.py",
        "4298c5d570a36a65dd3aa77aae6be13aaa61272e",
    ),
}


def main():
    env = os.environ.copy()
    with tempfile.TemporaryDirectory(prefix="waiter-tests-") as directory:
        for variable, (path, expected) in FILES.items():
            with urllib.request.urlopen(
                f"https://raw.githubusercontent.com/AstrBotDevs/AstrBot/v4.29.4/{path}",
                timeout=30,
            ) as response:
                content = response.read()
            blob = b"blob " + str(len(content)).encode() + b"\0" + content
            if hashlib.sha1(blob).hexdigest() != expected:
                raise RuntimeError(f"Upstream checksum mismatch: {path}")
            target = Path(directory) / f"{variable}.py"
            target.write_bytes(content)
            env[variable] = str(target)
        return subprocess.call(
            [
                sys.executable,
                "-W",
                "error::RuntimeWarning",
                "-m",
                "unittest",
                "discover",
                "-s",
                str(Path(__file__).parent),
                "-v",
            ],
            env=env,
        )


if __name__ == "__main__":
    raise SystemExit(main())
