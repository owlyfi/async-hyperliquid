from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


def _release_text() -> str:
    return RELEASE.read_text(encoding="utf-8")


def test_release_workflow_is_tag_only_and_fail_closed() -> None:
    workflow = _release_text()
    assert 'tags: ["v*"]' in workflow
    assert "workflow_dispatch" not in workflow
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


def test_release_workflow_pins_every_external_action() -> None:
    workflow = _release_text()
    expected = {
        "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd",
        "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
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


def test_published_project_urls_use_current_repository() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    urls = project["urls"]
    assert all("github.com/owlyfi/async-hyperliquid" in url for url in urls.values())


def test_release_runbook_covers_setup_and_recovery() -> None:
    runbook = (ROOT / "docs" / "releasing.md").read_text()
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
        "yank",
    }
    for phrase in required:
        assert phrase in runbook
