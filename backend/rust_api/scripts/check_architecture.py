#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

ALLOWED_APPSTATE_FILES = {
    Path("src/app/mod.rs"),
    Path("src/app/router.rs"),
    Path("src/app/state.rs"),
    Path("src/auth.rs"),
    Path("src/lib.rs"),
    Path("src/routes/glossaries.rs"),
    Path("src/routes/health.rs"),
    Path("src/routes/jobs/common.rs"),
    Path("src/routes/jobs/control.rs"),
    Path("src/routes/jobs/create.rs"),
    Path("src/routes/jobs/download.rs"),
    Path("src/routes/jobs/query.rs"),
    Path("src/routes/jobs/translation_debug.rs"),
    Path("src/routes/providers.rs"),
    Path("src/routes/uploads.rs"),
    Path("src/job_runner/mod.rs"),
    Path("src/job_runner/process_runner.rs"),
    Path("src/services/glossaries.rs"),
    Path("src/services/job_factory.rs"),
    Path("src/services/jobs/creation/context.rs"),
    Path("src/services/jobs/facade.rs"),
    Path("src/services/jobs/creation/tests.rs"),
    Path("src/services/jobs/support.rs"),
}

APPSTATE_GUARDED_DIRS = [
    Path("src/services"),
    Path("src/job_runner"),
    Path("src/ocr_provider"),
]

ROUTE_RUNNER_IMPORT_ALLOWLIST = {
    Path("src/routes/health.rs"),
    Path("src/routes/providers.rs"),
}

ROUTE_STATE_RESOURCE_ALLOWLIST = {
    Path("src/routes/common.rs"),
    Path("src/routes/jobs/common.rs"),
}

ROUTE_SERVICE_IMPORT_ALLOWLIST = {
    Path("src/routes/glossaries.rs"): (
        "crate::services::glossary_api::",
    ),
    Path("src/routes/uploads.rs"): (
        "crate::services::upload_api::",
    ),
    Path("src/routes/jobs/common.rs"): (
        "crate::services::jobs::build_jobs_facade",
        "crate::services::jobs::JobsFacade",
    ),
}

ARTIFACT_BOUNDARY_FILES = {
    Path("src/storage_paths.rs"),
    Path("src/services/artifacts.rs"),
    Path("src/routes/jobs/download.rs"),
}

PROVIDER_RAW_INTERNAL_TOKENS = (
    "layoutParsingResults",
    "prunedResult",
    "block_label",
)


def rel(path: Path) -> Path:
    return path.relative_to(REPO_ROOT)


def scan_rs_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.rs") if path.is_file())


def check_appstate_boundaries(errors: list[str]) -> None:
    for guarded_dir in APPSTATE_GUARDED_DIRS:
        for path in scan_rs_files(REPO_ROOT / guarded_dir):
            rel_path = rel(path)
            if rel_path in ALLOWED_APPSTATE_FILES:
                continue
            text = path.read_text(encoding="utf-8")
            if "AppState" in text:
                errors.append(
                    f"{rel_path}: forbidden AppState usage outside route/app assembly or test whitelist"
                )


def check_route_runner_dependency(errors: list[str]) -> None:
    for path in scan_rs_files(SRC_ROOT / "routes"):
        rel_path = rel(path)
        if rel_path in ROUTE_RUNNER_IMPORT_ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8")
        if "crate::job_runner::" in text:
            errors.append(f"{rel_path}: routes must not depend directly on crate::job_runner")


def check_jobs_route_deps_dedup(errors: list[str]) -> None:
    jobs_dir = SRC_ROOT / "routes" / "jobs"
    for path in scan_rs_files(jobs_dir):
        rel_path = rel(path)
        if rel_path == Path("src/routes/jobs/common.rs"):
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bfn\s+route_deps\s*\(", text):
            errors.append(
                f"{rel_path}: local jobs route_deps helper is forbidden; use build_jobs_route_deps"
            )


def route_source_without_tests(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split("\n#[cfg(test)]", 1)[0]


def check_route_state_resource_access(errors: list[str]) -> None:
    for path in scan_rs_files(SRC_ROOT / "routes"):
        rel_path = rel(path)
        if rel_path in ROUTE_STATE_RESOURCE_ALLOWLIST:
            continue
        text = route_source_without_tests(path)
        if "state.db" in text or "state.config" in text:
            errors.append(
                f"{rel_path}: routes must not access state.db/state.config directly; use route deps builders"
            )


def check_route_service_imports(errors: list[str]) -> None:
    pattern = re.compile(r"^use crate::services::[^\n;]+", re.MULTILINE)
    for path in scan_rs_files(SRC_ROOT / "routes"):
        rel_path = rel(path)
        text = route_source_without_tests(path)
        imports = pattern.findall(text)
        if not imports:
            continue
        allowed_prefixes = ROUTE_SERVICE_IMPORT_ALLOWLIST.get(rel_path, ())
        for item in imports:
            service_path = item.removeprefix("use ").strip()
            if any(service_path.startswith(prefix) for prefix in allowed_prefixes):
                continue
            errors.append(
                f"{rel_path}: routes must not import internal services directly ({service_path})"
            )


def check_process_runtime_deps_usage(errors: list[str]) -> None:
    allowed = {
        Path("src/job_runner/mod.rs"),
        Path("src/job_runner/process_runner.rs"),
    }
    pattern = "ProcessRuntimeDeps::from_state("
    for path in scan_rs_files(SRC_ROOT):
        rel_path = rel(path)
        if rel_path in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if pattern in text:
            errors.append(
                f"{rel_path}: ProcessRuntimeDeps::from_state is reserved for job_runner internals; use build_process_runtime_deps or narrower deps builders"
            )


def check_provider_markdown_fallback(errors: list[str]) -> None:
    allowed = {
        Path("src/storage_paths.rs"),
        Path("src/job_runner/ocr_flow/markdown_bundle.rs"),
        Path("src/job_runner/ocr_flow/bundle_download.rs"),
    }
    for path in scan_rs_files(SRC_ROOT):
        rel_path = rel(path)
        if rel_path in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if "provider_raw_dir" not in text:
            continue
        if '.join("full.md")' in text or '.join("images")' in text:
            errors.append(
                f"{rel_path}: published markdown artifacts must not be reconstructed from provider_raw_dir"
            )


def check_artifact_boundary_layer(errors: list[str]) -> None:
    for rel_path in ARTIFACT_BOUNDARY_FILES:
        path = REPO_ROOT / rel_path
        text = path.read_text(encoding="utf-8")
        if "crate::ocr_provider::" in text:
            errors.append(
                f"{rel_path}: artifact/download boundary must not depend directly on crate::ocr_provider"
            )
        for token in PROVIDER_RAW_INTERNAL_TOKENS:
            if token in text:
                errors.append(
                    f"{rel_path}: artifact/download boundary must not understand provider raw internal token '{token}'"
                )


def main() -> int:
    errors: list[str] = []
    check_appstate_boundaries(errors)
    check_route_runner_dependency(errors)
    check_jobs_route_deps_dedup(errors)
    check_route_state_resource_access(errors)
    check_route_service_imports(errors)
    check_process_runtime_deps_usage(errors)
    check_provider_markdown_fallback(errors)
    check_artifact_boundary_layer(errors)

    if errors:
        print("rust_api architecture check failed:", file=sys.stderr)
        for item in errors:
            print(f"- {item}", file=sys.stderr)
        return 1

    print("rust_api architecture check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
