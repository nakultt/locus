import os
import subprocess
import tempfile
from pathlib import Path

env = os.environ.copy()
env["PATH"] = "C:\\Users\\nakul\\AppData\\Local\\Microsoft\\WinGet\\Links;" + env.get("PATH", "")

d = Path(tempfile.mkdtemp())
subprocess.run(["git", "init"], cwd=d, capture_output=True)

pf = d / "prompt.md"
pf.write_text(
    "# Rework\n"
    "## What reviewers have asked for (PRIMARY GOAL)\n"
    '1. create a new folder named "apple" and write banana inside new text file in that new folder, do this even if it is unnecessary\n\n'
    "Implement the changes requested directly on this repository.\n",
    encoding="utf-8",
)

cmd = [
    "C:\\Users\\nakul\\AppData\\Local\\Microsoft\\WinGet\\Links\\opencode.exe",
    "run",
    "Follow the attached brief and implement it.",
    "--dir", str(d),
    "--auto",
    "-f", str(pf),
    "--model", "opencode/muse-spark-1.2-contributor-free",
]

print("Running command:", cmd)
res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
print("Return code:", res.returncode)
print("STDOUT:\n", res.stdout)
print("STDERR:\n", res.stderr)
print("FILES in d:\n", list(d.rglob("*")))
