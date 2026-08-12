"""
PR Security Scanning
Two independent layers, deliberately kept separate.

Layer 1 (Semgrep, Gitleaks) is deterministic rule matching. Its findings are
reported as CONFIRMED.

Layer 2 (LLM) catches logic-level problems no rule encodes -- missing authz,
injection through an untrusted path, unsafe deserialization. Its findings are
reported as UNVERIFIED.

The two lists are never merged. An LLM asserting a confirmed vulnerability that
turns out to be imaginary is worse than missing one: it costs a reviewer real
time and it only has to happen once for the team to start ignoring the bot.

Layer 2 runs on a bare LLM with no tools bound. Diff content is attacker-
influenced -- anyone who can open a PR controls it -- so it must never reach a
model that can act on what it reads.
"""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

from app.schemas import FindingSource, SecurityFinding, SecuritySeverity
from app.services.llm import get_llm

# Semgrep severity -> ours
_SEMGREP_SEVERITY = {
    "ERROR": SecuritySeverity.high,
    "WARNING": SecuritySeverity.medium,
    "INFO": SecuritySeverity.low,
}

SEMGREP_TIMEOUT_SECONDS = 120


def _find_binary(name: str) -> str | None:
    """
    Locate an executable, checking the running interpreter's environment first.

    A plain shutil.which() only searches PATH, which misses tools installed into
    the active virtualenv when the server was started without activating it --
    the common case under a process manager.
    """
    # Same directory as the current interpreter (venv Scripts/ or bin/).
    bin_dir = Path(sys.executable).parent
    for candidate in (bin_dir / name, bin_dir / f"{name}.exe"):
        if candidate.is_file():
            return str(candidate)

    return shutil.which(name)


def semgrep_available() -> bool:
    """Whether the semgrep binary can be found."""
    return _find_binary("semgrep") is not None


async def run_semgrep(files: dict[str, str]) -> tuple[list[SecurityFinding], str | None]:
    """
    Run Semgrep over the changed files.

    Takes real file contents, not a diff. Semgrep parses source into an AST and
    matches structurally; handed a unified diff it silently finds nothing, because
    a .diff is not valid source in any language. Files are reconstructed under a
    temp tree preserving their original paths and extensions so language
    detection and the rules both work.

    Args:
        files: Mapping of repo-relative path -> file content

    Returns:
        (findings, error message or None)
    """
    semgrep_bin = _find_binary("semgrep")
    if not semgrep_bin:
        return [], "semgrep not installed; skipping deterministic scan"

    if not files:
        return [], None

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for rel_path, content in files.items():
            # Guard against traversal in attacker-controlled paths.
            safe_rel = Path(rel_path.replace("\\", "/"))
            if safe_rel.is_absolute() or ".." in safe_rel.parts:
                continue
            target = root / safe_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", errors="replace")

        try:
            process = await asyncio.create_subprocess_exec(
                semgrep_bin,
                "--config", "p/security-audit",
                "--config", "p/secrets",
                "--json",
                "--quiet",
                "--no-git-ignore",
                str(root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=SEMGREP_TIMEOUT_SECONDS
            )
        except TimeoutError:
            return [], "semgrep timed out"
        except Exception as e:
            return [], f"semgrep failed: {e}"

        temp_root = str(root)

    try:
        payload = json.loads(stdout.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        return [], "semgrep returned unparseable output"

    findings: list[SecurityFinding] = []
    for result in payload.get("results", []):
        extra = result.get("extra", {})
        metadata = extra.get("metadata", {})

        # Report the repo-relative path, not our scratch directory.
        path = result.get("path", "unknown")
        try:
            path = str(Path(path).relative_to(temp_root)).replace("\\", "/")
        except (ValueError, TypeError):
            pass

        check_id = result.get("check_id", "")
        findings.append(SecurityFinding(
            source=FindingSource.semgrep,
            severity=_SEMGREP_SEVERITY.get(
                extra.get("severity", "WARNING"), SecuritySeverity.medium
            ),
            title=(
                metadata.get("shortDescription")
                or check_id.rsplit(".", 1)[-1].replace("-", " ").capitalize()
                or "Finding"
            ),
            file_path=path,
            line=result.get("start", {}).get("line"),
            description=extra.get("message", "").strip(),
            rule_id=check_id or None,
        ))

    return findings, None


def gitleaks_available() -> bool:
    """Whether the gitleaks binary can be found."""
    return _find_binary("gitleaks") is not None


async def run_gitleaks(diff_text: str) -> tuple[list[SecurityFinding], str | None]:
    """
    Scan for committed credentials.

    Findings report the location only. The secret value is never captured or
    echoed -- posting it into a PR comment or Slack message would widen the
    exposure we are reporting.
    """
    gitleaks_bin = _find_binary("gitleaks")
    if not gitleaks_bin:
        return [], "gitleaks not installed; skipping secret scan"

    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "changes.diff"
        report = Path(tmpdir) / "report.json"
        target.write_text(diff_text, encoding="utf-8")

        try:
            process = await asyncio.create_subprocess_exec(
                gitleaks_bin, "detect",
                "--source", str(target),
                "--no-git",
                "--report-format", "json",
                "--report-path", str(report),
                "--exit-code", "0",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), timeout=60)
        except TimeoutError:
            return [], "gitleaks timed out"
        except Exception as e:
            return [], f"gitleaks failed: {e}"

        if not report.exists():
            return [], None

        try:
            leaks = json.loads(report.read_text(encoding="utf-8") or "[]")
        except json.JSONDecodeError:
            return [], "gitleaks returned unparseable output"

    # Gitleaks scanned one concatenated .diff, so every hit reports that temp
    # path. Map diff line numbers back to the real files they belong to.
    line_map = _map_diff_lines(diff_text)

    return [
        SecurityFinding(
            source=FindingSource.gitleaks,
            severity=SecuritySeverity.critical,
            title=f"Possible {leak.get('RuleID', 'credential')} committed",
            file_path=line_map.get(leak.get("StartLine") or 0, "changed files"),
            line=None,  # The diff offset would mislead; the file is what matters.
            # Location only. No secret value, by design.
            description=(
                "A value matching a credential pattern was detected. "
                "Rotate it and remove it from the diff."
            ),
            rule_id=leak.get("RuleID"),
        )
        for leak in leaks
    ], None


def _map_diff_lines(diff_text: str) -> dict[int, str]:
    """
    Map each line number in a unified diff to the file that line belongs to.

    Gitleaks reports offsets into the diff we handed it; without this the
    finding points at a temp path instead of the file a reviewer must fix.
    """
    mapping: dict[int, str] = {}
    current = "changed files"

    for index, line in enumerate(diff_text.splitlines(), start=1):
        if line.startswith("+++ b/"):
            current = line[6:].strip()
        elif line.startswith("+++ "):
            current = line[4:].strip()
        mapping[index] = current

    return mapping


LLM_REVIEW_PROMPT = """You are a security reviewer examining a pull request diff.

A deterministic scanner has already run. Its findings are listed below; do not \
repeat them. Look for problems static rules miss: missing authorization checks, \
injection through untrusted input, unsafe deserialization, secrets read from the \
wrong place, broken access control, race conditions on shared state.

Existing scanner findings:
{semgrep_summary}

{document_context}
Diff under review:
```
{diff}
```

Report only issues you can point to a specific line for. If you find nothing, \
return an empty array. Do not speculate; a false alarm wastes a reviewer's time.

Return ONLY a JSON array, no prose:
[
  {{
    "severity": "critical|high|medium|low",
    "title": "Short description",
    "file_path": "path/to/file.py",
    "line": 42,
    "description": "What is wrong and why it matters."
  }}
]"""


async def run_llm_review(
    diff_text: str,
    semgrep_findings: list[SecurityFinding],
    document_context: str = "",
) -> tuple[list[SecurityFinding], str | None]:
    """
    LLM pass for logic-level issues.

    Runs on a bare LLM with no tools bound. The diff and any supplied documents
    are untrusted input; a model reading them must not be able to act on
    instructions embedded in them.

    Args:
        document_context: Internal design docs describing intended behaviour,
            so the review can flag a diff that contradicts the spec rather than
            judging it in isolation.
    """
    if semgrep_findings:
        semgrep_summary = "\n".join(
            f"- {f.file_path}:{f.line} {f.title}" for f in semgrep_findings
        )
    else:
        semgrep_summary = "(none)"

    try:
        llm = get_llm(temperature=0)
        chain = ChatPromptTemplate.from_template(LLM_REVIEW_PROMPT) | llm
        response = await chain.ainvoke({
            "semgrep_summary": semgrep_summary,
            "document_context": document_context,
            "diff": diff_text,
        })
    except Exception as e:
        return [], f"LLM review failed: {e}"

    content = response.content if isinstance(response.content, str) else str(response.content)
    content = content.strip()

    # Local models frequently wrap JSON in a markdown fence.
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        content = content.strip()

    try:
        raw_findings = json.loads(content)
    except json.JSONDecodeError:
        return [], "LLM review returned unparseable output"

    if not isinstance(raw_findings, list):
        return [], "LLM review did not return a list"

    findings: list[SecurityFinding] = []
    for item in raw_findings:
        if not isinstance(item, dict):
            continue
        try:
            severity = SecuritySeverity(str(item.get("severity", "medium")).lower())
        except ValueError:
            severity = SecuritySeverity.medium

        findings.append(SecurityFinding(
            source=FindingSource.llm,
            severity=severity,
            title=str(item.get("title", "Potential issue")),
            file_path=str(item.get("file_path", "unknown")),
            line=item.get("line") if isinstance(item.get("line"), int) else None,
            description=str(item.get("description", "")),
        ))

    return findings, None


async def scan_changes(
    files: dict[str, str],
    diff_text: str,
    enable_llm_review: bool = True,
    document_context: str = "",
) -> tuple[list[SecurityFinding], list[SecurityFinding], list[str]]:
    """
    Run the full two-layer scan.

    Args:
        files: Changed files as path -> content. Semgrep needs real source.
        diff_text: Unified diff, used for secret scanning and the LLM review,
            where "what changed" matters more than whole-file context.
        enable_llm_review: Whether to run the unverified LLM pass.

    Returns:
        (confirmed findings, unverified findings, non-fatal error messages)
    """
    errors: list[str] = []

    semgrep_findings, semgrep_error = await run_semgrep(files)
    if semgrep_error:
        errors.append(semgrep_error)

    gitleaks_findings, gitleaks_error = await run_gitleaks(diff_text)
    if gitleaks_error:
        errors.append(gitleaks_error)

    confirmed = gitleaks_findings + semgrep_findings

    unverified: list[SecurityFinding] = []
    if enable_llm_review:
        unverified, llm_error = await run_llm_review(
            diff_text, semgrep_findings, document_context
        )
        if llm_error:
            errors.append(llm_error)

    return confirmed, unverified, errors
