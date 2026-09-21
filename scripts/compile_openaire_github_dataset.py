"""Compile the OpenAIRE software dump into a GitHub-repository dataset.

Source:
https://zenodo.org/records/12819872/files/software.tar?download=1

The OpenAIRE Software schema defines codeRepositoryUrl as the source-code
repository URL. This script keeps records whose codeRepositoryUrl identifies a
GitHub repository, normalizes the URL to https://github.com/OWNER/REPO, and
creates both record-level and deduplicated repository-level outputs.

No AI or fuzzy URL inference is used.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import random
import re
import shutil
import tarfile
import tempfile
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

DEFAULT_SOURCE_URL = (
    "https://zenodo.org/records/12819872/files/software.tar?download=1"
)
DEFAULT_OUTPUT_DIR = Path("data/openaire_zenodo_12819872")
DEFAULT_SAMPLE_SIZE = 100
DEFAULT_SAMPLE_SEED = 42

GITHUB_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
GITHUB_RESERVED_ROOTS = {
    "about", "apps", "collections", "contact", "customer-stories", "enterprise",
    "events", "explore", "features", "issues", "join", "login", "marketplace",
    "new", "notifications", "orgs", "organizations", "pricing", "pulls",
    "search", "security", "settings", "site", "sponsors", "topics", "trending",
    "users",
}


def _iter_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                yield item


def normalize_github_repo_url(value: str) -> str | None:
    """Normalize a GitHub URL to https://github.com/OWNER/REPO.

    Supports normal HTTP(S), git://, ssh://git@github.com/... and scp-like
    git@github.com:OWNER/REPO.git forms. Deep links such as /blob/, /tree/,
    /issues/, etc. are reduced to the repository root.
    """
    if not value:
        return None

    raw = value.strip().strip("<>[](){}.,;")
    if not raw:
        return None

    # scp-like Git SSH syntax
    if raw.lower().startswith("git@github.com:"):
        path = raw.split(":", 1)[1]
        parts = [p for p in path.split("/") if p]
    else:
        # Some metadata use git+https://...
        if raw.lower().startswith("git+"):
            raw = raw[4:]
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if host not in {"github.com", "www.github.com"}:
            return None
        parts = [p for p in parsed.path.split("/") if p]

    if len(parts) < 2:
        return None

    owner = parts[0]
    repository = parts[1]
    if repository.lower().endswith(".git"):
        repository = repository[:-4]

    if (
        not owner
        or not repository
        or owner.lower() in GITHUB_RESERVED_ROOTS
        or not GITHUB_COMPONENT_RE.fullmatch(owner)
        or not GITHUB_COMPONENT_RE.fullmatch(repository)
    ):
        return None

    return f"https://github.com/{owner}/{repository}"


def _authors(record: dict[str, Any]) -> list[str]:
    values = record.get("authors")
    if values is None:
        values = record.get("author")

    result: list[str] = []
    if isinstance(values, list):
        for author in values:
            if not isinstance(author, dict):
                continue
            name = (
                author.get("fullName")
                or author.get("fullname")
                or " ".join(
                    part
                    for part in [author.get("name"), author.get("surname")]
                    if part
                )
            )
            if name:
                result.append(str(name).strip())
    return result


def _pids(record: dict[str, Any]) -> list[str]:
    values = record.get("pids")
    if values is None:
        values = record.get("pid")
    result: list[str] = []
    if isinstance(values, list):
        for pid in values:
            if not isinstance(pid, dict):
                continue
            scheme = pid.get("scheme")
            value = pid.get("value")
            if value:
                result.append(f"{scheme}:{value}" if scheme else str(value))
    return result


def compact_record(
    record: dict[str, Any],
    original_repo_url: str,
    github_repo_url: str,
) -> dict[str, Any]:
    """Keep metadata useful for sampling, auditing and later analysis."""
    return {
        "openaire_id": record.get("id"),
        "type": record.get("type"),
        "main_title": record.get("mainTitle") or record.get("maintitle"),
        "sub_title": record.get("subTitle") or record.get("subtitle"),
        "publication_date": (
            record.get("publicationDate") or record.get("publicationdate")
        ),
        "publisher": record.get("publisher"),
        "version": record.get("version"),
        "programming_language": (
            record.get("programmingLanguage") or record.get("programminglanguage")
        ),
        "authors": _authors(record),
        "pids": _pids(record),
        "code_repository_url_original": original_repo_url,
        "github_repository_url": github_repo_url,
    }


def download_source(url: str, destination: Path) -> None:
    print(f"Downloading {url}", flush=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "research-process-steps-dataset-builder/0.1"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    print(
        f"Downloaded {destination.stat().st_size:,} bytes to {destination}",
        flush=True,
    )


def iter_software_records(tar_path: Path) -> Iterable[dict[str, Any]]:
    """Stream JSON-lines records from gz members inside software.tar."""
    with tarfile.open(tar_path, mode="r:*") as archive:
        for member in archive:
            if not member.isfile():
                continue

            extracted = archive.extractfile(member)
            if extracted is None:
                continue

            print(f"Reading {member.name}", flush=True)
            if member.name.lower().endswith(".gz"):
                stream = gzip.GzipFile(fileobj=extracted)
            else:
                stream = extracted

            with io.TextIOWrapper(stream, encoding="utf-8", errors="replace") as text:
                for line_number, line in enumerate(text, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(
                            f"Invalid JSON in {member.name}:{line_number}: {exc}"
                        ) from exc
                    if isinstance(record, dict):
                        yield record


def github_urls_from_record(record: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (original, normalized) pairs from codeRepositoryUrl only."""
    value = record.get("codeRepositoryUrl")
    if value is None:
        value = record.get("coderepositoryurl")

    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for original in _iter_values(value):
        normalized = normalize_github_repo_url(original)
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            result.append((original, normalized))
    return result


def write_outputs(
    source_tar: Path,
    output_dir: Path,
    sample_size: int,
    sample_seed: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records_path = output_dir / "github_software_records.jsonl"
    repositories_path = output_dir / "github_repositories.csv"
    sample_path = output_dir / f"validation_sample_{sample_size}.csv"
    summary_path = output_dir / "summary.json"

    total_records = 0
    records_with_code_repo = 0
    github_records = 0
    invalid_or_non_github_code_repo = 0
    repository_records: dict[str, list[dict[str, Any]]] = defaultdict(list)

    with records_path.open("w", encoding="utf-8") as records_out:
        for record in iter_software_records(source_tar):
            total_records += 1
            raw_code_repo = (
                record.get("codeRepositoryUrl")
                if "codeRepositoryUrl" in record
                else record.get("coderepositoryurl")
            )
            raw_values = list(_iter_values(raw_code_repo))
            if raw_values:
                records_with_code_repo += 1

            github_pairs = github_urls_from_record(record)
            if raw_values and not github_pairs:
                invalid_or_non_github_code_repo += 1

            for original_url, github_url in github_pairs:
                compact = compact_record(record, original_url, github_url)
                records_out.write(
                    json.dumps(compact, ensure_ascii=False, sort_keys=True) + "\n"
                )
                repository_records[github_url.lower()].append(compact)
                github_records += 1

            if total_records % 100_000 == 0:
                print(
                    f"Processed {total_records:,} software records; "
                    f"{github_records:,} GitHub record links",
                    flush=True,
                )

    repository_rows: list[dict[str, Any]] = []
    for key in sorted(repository_records):
        grouped = repository_records[key]
        representative = grouped[0]
        repository_rows.append(
            {
                "github_repository_url": representative["github_repository_url"],
                "record_count": len(grouped),
                "representative_title": representative.get("main_title") or "",
                "openaire_ids": " | ".join(
                    sorted(
                        {
                            str(row["openaire_id"])
                            for row in grouped
                            if row.get("openaire_id")
                        }
                    )
                ),
                "programming_languages": " | ".join(
                    sorted(
                        {
                            str(row["programming_language"])
                            for row in grouped
                            if row.get("programming_language")
                        }
                    )
                ),
                "publication_dates": " | ".join(
                    sorted(
                        {
                            str(row["publication_date"])
                            for row in grouped
                            if row.get("publication_date")
                        }
                    )
                ),
            }
        )

    fieldnames = [
        "github_repository_url",
        "record_count",
        "representative_title",
        "openaire_ids",
        "programming_languages",
        "publication_dates",
    ]
    with repositories_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(repository_rows)

    rng = random.Random(sample_seed)
    actual_sample_size = min(sample_size, len(repository_rows))
    sampled = rng.sample(repository_rows, actual_sample_size)
    sampled.sort(key=lambda row: row["github_repository_url"].lower())

    sample_fieldnames = [
        "sample_id",
        *fieldnames,
        "manual_collection",
        "manual_processing",
        "manual_implementation",
        "manual_experimentation",
        "manual_evaluation",
        "manual_dissemination",
        "annotation_notes",
    ]
    with sample_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=sample_fieldnames)
        writer.writeheader()
        for index, row in enumerate(sampled, start=1):
            writer.writerow(
                {
                    "sample_id": f"S{index:03d}",
                    **row,
                    "manual_collection": "",
                    "manual_processing": "",
                    "manual_implementation": "",
                    "manual_experimentation": "",
                    "manual_evaluation": "",
                    "manual_dissemination": "",
                    "annotation_notes": "",
                }
            )

    summary = {
        "source": {
            "zenodo_record": "https://zenodo.org/records/12819872",
            "software_tar_url": DEFAULT_SOURCE_URL,
            "source_tar_size_bytes": source_tar.stat().st_size,
        },
        "filter": {
            "field": "codeRepositoryUrl",
            "host": "github.com",
            "normalization": "https://github.com/OWNER/REPO",
        },
        "counts": {
            "software_records_total": total_records,
            "records_with_code_repository_url": records_with_code_repo,
            "github_record_links": github_records,
            "unique_github_repositories": len(repository_rows),
            "non_github_or_invalid_code_repository_urls": (
                invalid_or_non_github_code_repo
            ),
            "validation_sample_size": actual_sample_size,
        },
        "sampling": {
            "method": "simple random sample without replacement",
            "population": "deduplicated normalized GitHub repositories",
            "seed": sample_seed,
            "requested_size": sample_size,
        },
        "outputs": {
            "record_level_jsonl": str(records_path),
            "repository_level_csv": str(repositories_path),
            "validation_sample_csv": str(sample_path),
        },
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary["counts"], indent=2), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download/parse the OpenAIRE software dump and keep software records "
            "whose codeRepositoryUrl points to a GitHub repository."
        )
    )
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument(
        "--source-tar",
        type=Path,
        help="Use an already downloaded software.tar instead of downloading it.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--sample-seed", type=int, default=DEFAULT_SAMPLE_SEED)
    args = parser.parse_args()

    if args.source_tar is not None:
        source_tar = args.source_tar
        if not source_tar.exists():
            raise SystemExit(f"Source tar does not exist: {source_tar}")
        write_outputs(
            source_tar,
            args.output_dir,
            args.sample_size,
            args.sample_seed,
        )
        return

    with tempfile.TemporaryDirectory(prefix="openaire-software-") as temp:
        source_tar = Path(temp) / "software.tar"
        download_source(args.source_url, source_tar)
        write_outputs(
            source_tar,
            args.output_dir,
            args.sample_size,
            args.sample_seed,
        )


if __name__ == "__main__":
    main()
