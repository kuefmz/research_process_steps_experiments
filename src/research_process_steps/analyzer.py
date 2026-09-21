"""GitHub repository analyzer using deterministic heuristics only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .heuristics import CONTENT_EXTENSIONS, RESEARCH_PROCESS_STEPS, RULES


DEFAULT_CONTENT_LIMIT = 250_000
DETECTION_THRESHOLD = 2
USER_AGENT = "research-process-steps/0.1"


def _parse_github_url(repository_url: str) -> tuple[str, str]:
    parsed = urlparse(repository_url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise ValueError("Expected a github.com repository URL.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("Expected a GitHub URL in the form https://github.com/OWNER/REPO.")

    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise ValueError("Could not determine repository owner and name.")
    return owner, repo


def _request_json(url: str, token: str | None = None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub request failed ({exc.code}): {detail}") from exc


def _request_text(url: str, token: str | None = None) -> str:
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _content_is_scannable(path: str) -> bool:
    name = Path(path).name.lower()
    if name in {"dockerfile", "makefile"}:
        return True
    return Path(name).suffix.lower() in CONTENT_EXTENSIONS


def analyze_file(path: str, content: str = "") -> dict[str, Any]:
    """Classify one repository file using explicit deterministic rules.

    A process step is emitted when its accumulated evidence score reaches the
    detection threshold. Content-only indicators are intentionally weak; this
    prevents a single incidental word from assigning a research step.
    """

    scores = {step: 0 for step in RESEARCH_PROCESS_STEPS}
    evidence: list[dict[str, Any]] = []

    for rule in RULES:
        haystack = path if rule.source == "path" else content
        if not haystack:
            continue
        match = rule.pattern.search(haystack)
        if not match:
            continue

        scores[rule.step] += rule.weight
        evidence.append(
            {
                "rule_id": rule.id,
                "step": rule.step,
                "source": rule.source,
                "weight": rule.weight,
                "matched_text": match.group(0)[:160],
                "description": rule.description,
            }
        )

    detected = [
        step for step in RESEARCH_PROCESS_STEPS if scores[step] >= DETECTION_THRESHOLD
    ]
    return {
        "path": path,
        "steps": detected,
        "unclassified": not detected,
        "scores": {step: score for step, score in scores.items() if score},
        "evidence": evidence,
    }


def analyze_github_repository(
    repository_url: str,
    *,
    token: str | None = None,
    ref: str | None = None,
    max_content_bytes: int = DEFAULT_CONTENT_LIMIT,
) -> dict[str, Any]:
    """Analyze every file in a GitHub repository and return per-file evidence."""

    owner, repo = _parse_github_url(repository_url)
    api_base = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}"
    metadata = _request_json(api_base, token)
    chosen_ref = ref or metadata["default_branch"]

    tree_url = f"{api_base}/git/trees/{quote(chosen_ref, safe='')}?recursive=1"
    tree = _request_json(tree_url, token)
    if tree.get("truncated"):
        raise RuntimeError(
            "GitHub returned a truncated recursive tree. "
            "Use a smaller repository/ref or extend the tree traversal implementation."
        )

    files = [item for item in tree.get("tree", []) if item.get("type") == "blob"]
    output_files: list[dict[str, Any]] = []

    for item in sorted(files, key=lambda value: value["path"].lower()):
        path = item["path"]
        size = int(item.get("size") or 0)
        content = ""
        content_scanned = False

        if _content_is_scannable(path) and size <= max_content_bytes:
            encoded_path = "/".join(quote(part, safe="") for part in path.split("/"))
            raw_url = (
                "https://raw.githubusercontent.com/"
                f"{quote(owner)}/{quote(repo)}/{quote(chosen_ref, safe='')}/{encoded_path}"
            )
            try:
                content = _request_text(raw_url, token)
                content_scanned = True
            except Exception:
                content = ""

        result = analyze_file(path, content)
        result.update(
            {
                "size_bytes": size,
                "content_scanned": content_scanned,
                "blob_sha": item.get("sha"),
            }
        )
        output_files.append(result)

    step_counts = {
        step: sum(step in record["steps"] for record in output_files)
        for step in RESEARCH_PROCESS_STEPS
    }

    return {
        "repository": {
            "url": repository_url,
            "full_name": f"{owner}/{repo}",
            "ref": chosen_ref,
            "commit_tree_sha": tree.get("sha"),
            "file_count": len(output_files),
        },
        "method": {
            "name": "deterministic_research_process_step_heuristics",
            "version": "0.1.0",
            "uses_ai": False,
            "multi_label": True,
            "detection_threshold": DETECTION_THRESHOLD,
            "max_content_bytes": max_content_bytes,
        },
        "summary": {
            "files_per_step": step_counts,
            "unclassified_files": sum(record["unclassified"] for record in output_files),
        },
        "files": output_files,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Identify research process steps for every file in a GitHub repository "
            "using deterministic heuristics only."
        )
    )
    parser.add_argument("repository_url", help="GitHub repository URL")
    parser.add_argument("--ref", help="Branch, tag, or commit; defaults to default branch")
    parser.add_argument(
        "--token",
        default=os.getenv("GITHUB_TOKEN"),
        help="GitHub token; defaults to GITHUB_TOKEN",
    )
    parser.add_argument(
        "--max-content-bytes",
        type=int,
        default=DEFAULT_CONTENT_LIMIT,
        help="Maximum file size for optional content-rule scanning",
    )
    parser.add_argument("-o", "--output", help="Write JSON output to this path")
    args = parser.parse_args()

    result = analyze_github_repository(
        args.repository_url,
        token=args.token,
        ref=args.ref,
        max_content_bytes=args.max_content_bytes,
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(rendered)


if __name__ == "__main__":
    main()
