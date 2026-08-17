from pathlib import Path
import tomllib

import yaml


ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


def _release_text() -> str:
    return RELEASE.read_text(encoding="utf-8")


def test_release_workflow_is_tag_only_and_fail_closed() -> None:
    workflow = _release_text()
    assert 'tags: ["v*"]' in workflow
    assert "workflow_dispatch" not in workflow
    assert "group: release-${{ github.repository }}" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "github.repository != 'owlyfi/async-hyperliquid'" in workflow
    assert '[[ "$tag" == "v$version" ]]' in workflow
    assert 'git merge-base --is-ancestor "$release_commit" origin/main' in workflow


def test_release_workflow_scopes_publish_permissions() -> None:
    workflow = _release_text()
    assert workflow.count("id-token: write") == 1
    assert workflow.count("contents: write") == 2
    assert "environment:\n      name: pypi" in workflow
    assert "PYPI_API_TOKEN" not in workflow
    assert "password:" not in workflow
    assert "skip-existing" not in workflow
    assert "enable-cache: true" not in workflow


def test_ci_checkout_does_not_persist_push_credentials() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert workflow.count("persist-credentials: false") == 2


def test_release_workflow_builds_and_shares_one_bundle() -> None:
    workflow = _release_text()
    assert workflow.count("uv build --no-sources --clear") == 1
    assert "sha256sum dist/* > SHA256SUMS" in workflow
    assert "release-bundle-${{ github.sha }}" in workflow
    assert "packages-dir: release-bundle/dist" in workflow
    pypi_job = workflow.split("  publish_pypi:", 1)[1].split(
        "  publish_github_release:", 1
    )[0]
    github_job = workflow.split("  publish_github_release:", 1)[1].split(
        "  verify_release:", 1
    )[0]
    assert "- create_draft_release" in pypi_job
    assert "- publish_pypi" in github_job


def test_github_assets_are_hash_verified_before_and_after_immutability() -> None:
    workflow = _release_text()
    publish_job = workflow.split("  publish_github_release:", 1)[1].split(
        "  verify_release:", 1
    )[0]
    verify_job = workflow.split("  verify_release:", 1)[1]
    for job in (publish_job, verify_job):
        assert "sha256sum --check SHA256SUMS" in job
        assert 'asset["digest"]' in job
        assert '"sha256:" + hashlib.sha256' in job


def test_release_body_is_compared_raw_before_and_after_publication() -> None:
    workflow = _release_text()
    publish_job = workflow.split("  publish_github_release:", 1)[1].split(
        "  verify_release:", 1
    )[0]
    verify_job = workflow.split("  verify_release:", 1)[1]
    raw_api = 'gh api "repos/${GH_REPO}/releases/tags/${TAG}"'
    extract_body = "jq -jr '.body'"
    compare_body = "cmp -s release-bundle/RELEASE_NOTES.md"

    for job in (publish_job, verify_job):
        assert raw_api in job
        assert extract_body in job
        assert compare_body in job
        assert "mktemp -d" in job
        assert "set -euo pipefail" in job

    assert workflow.count(raw_api) == 2
    assert workflow.count(extract_body) == 2
    assert workflow.count(compare_body) == 2
    assert "--jq .body" not in workflow


def test_release_workflow_pins_every_external_action() -> None:
    workflow = _release_text()
    expected = {
        "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
        "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
        "pypa/gh-action-pypi-publish@ed0c53931b1dc9bd32cbe73a98c7f6766f8a527e",
    }
    for action in expected:
        assert action in workflow
    for line in workflow.splitlines():
        if "uses:" in line and not line.strip().startswith("#"):
            ref = line.split("uses:", 1)[1].strip().split("#", 1)[0].strip()
            assert "@" in ref
            assert len(ref.rsplit("@", 1)[1]) == 40


def test_ci_runs_for_pull_requests_and_branch_pushes_only() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "pull_request:" in workflow
    assert 'branches: ["**"]' in workflow
    assert "tags:" not in workflow


def test_workflows_install_the_benchmark_group_before_type_checking_it() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    ci_test_job = ci.split("  test:", 1)[1].split("  package:", 1)[0]
    release = _release_text()
    release_build_job = release.split("  test_and_build:", 1)[1].split(
        "  create_draft_release:", 1
    )[0]
    sync = "uv sync --locked --dev --group benchmark"
    assert sync in ci_test_job
    assert sync in release_build_job
    assert release_build_job.index(sync) < release_build_job.index(
        "scripts/extract_release_notes.py"
    )


def test_markdown_parser_is_a_dev_only_dependency() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependency = "markdown-it-py>=4.2.0,<5.0.0"

    assert dependency in configuration["dependency-groups"]["dev"]
    assert all(
        not item.startswith("markdown-it-py")
        for item in configuration["project"]["dependencies"]
    )


def test_workflows_install_locked_docs_and_build_warning_free_html() -> None:
    expected_sync = "uv sync --locked --dev --group benchmark --group docs"
    expected_build = (
        "uv run --frozen --group docs sphinx-build -W --keep-going -b html "
        "docs docs/_build/html"
    )
    workflows = (
        (ROOT / ".github" / "workflows" / "ci.yml", "test"),
        (RELEASE, "test_and_build"),
    )

    for path, job_name in workflows:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        runs = {
            step["run"] for step in workflow["jobs"][job_name]["steps"] if "run" in step
        }

        assert expected_sync in runs
        assert expected_build in runs


def test_workflow_smoke_tests_import_the_current_public_types() -> None:
    workflows = "\n".join(
        (ROOT / ".github" / "workflows" / name).read_text()
        for name in ("ci.yml", "release.yml")
    )
    assert "from async_hyperliquid.types import LimitOrder, Network" not in workflows
    assert (
        workflows.count("from async_hyperliquid.types import LimitOrderType, Network")
        == 5
    )


def test_published_project_urls_use_current_repository() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    urls = project["urls"]

    assert urls["Documentation"] == "https://async-hyperliquid.readthedocs.io/"
    assert all(
        "github.com/owlyfi/async-hyperliquid" in url
        for name, url in urls.items()
        if name != "Documentation"
    )


def test_release_runbook_covers_setup_and_recovery() -> None:
    runbook = (ROOT / "dev-docs" / "releasing.md").read_text()
    required = {
        "Trusted Publishing",
        "owlyfi",
        "release.yml",
        "Environment `pypi`",
        "Enable release immutability",
        "git tag -a",
        "git push origin",
        "Re-run failed jobs",
        "SHA256SUMS",
        "partial upload",
        "yank",
    }
    for phrase in required:
        assert phrase in runbook


def test_release_workflow_uses_only_changelog_release_notes() -> None:
    workflow = _release_text()
    build_job = workflow.split("  test_and_build:", 1)[1].split(
        "  create_draft_release:", 1
    )[0]
    draft_job = workflow.split("  create_draft_release:", 1)[1].split(
        "  publish_pypi:", 1
    )[0]
    assert "--generate-notes" not in workflow
    assert "scripts/extract_release_notes.py" in build_job
    assert '--version "$VERSION"' in build_job
    assert "--output RELEASE_NOTES.md" in build_job
    assert "\n            RELEASE_NOTES.md" in build_job
    assert "--notes-file release-bundle/RELEASE_NOTES.md" in draft_job
    assert "release-bundle/RELEASE_NOTES.md \\" not in draft_job


def test_ci_and_release_static_check_release_tooling() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    release = _release_text()
    for workflow in (ci, release):
        assert "uv run ruff check src tests benchmarks scripts" in workflow
        assert "uv run ty check scripts" in workflow
