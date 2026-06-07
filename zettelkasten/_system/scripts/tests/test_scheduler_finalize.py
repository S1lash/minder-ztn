"""End-to-end tests for the scheduler single-commit protocol.

Covers stage.sh + finalize-tick.sh + ship-failure-note.sh in real git
worktrees with a bare origin remote, so regressions in any of:

  - engine-path filtering (via _classify_paths.py + .engine-manifest.yml)
  - heuristic commit message derivation
  - partial-tick recovery via reset --soft fold
  - refusal on owner non-scheduled commits ahead
  - ship-failure-note local-only fallback

surface as test failures rather than as drift in production scheduler logs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEDULER_DIR = REPO_ROOT / "scripts" / "scheduler"
MANIFEST = REPO_ROOT / ".engine-manifest.yml"


def _git(cwd: Path, *args: str, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    full_env.update({
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    })
    if env:
        full_env.update(env)
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env=full_env,
    )


def _run_script(cwd: Path, script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", f"scripts/scheduler/{script}", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    work.mkdir()

    _git(work, "init", "-q", "-b", "main")
    _git(work, "remote", "add", "origin", str(origin))

    scheduler_dst = work / "scripts" / "scheduler"
    scheduler_dst.mkdir(parents=True)
    for name in (
        "stage.sh",
        "finalize-tick.sh",
        "ship-failure-note.sh",
        "_classify_paths.py",
    ):
        shutil.copy(SCHEDULER_DIR / name, scheduler_dst / name)
    shutil.copy(MANIFEST, work / ".engine-manifest.yml")

    (work / "zettelkasten" / "_records").mkdir(parents=True)
    (work / "zettelkasten" / "_system" / "state").mkdir(parents=True)

    _git(work, "add", ".engine-manifest.yml", "scripts/scheduler/")
    _git(work, "commit", "-q", "-m", "initial")
    _git(work, "push", "-q", "-u", "origin", "main")
    return work


def test_single_commit_for_mixed_staging(repo: Path) -> None:
    (repo / "zettelkasten/_records/r1.md").write_text("rec1\n")
    (repo / "zettelkasten/_records/r2.md").write_text("rec2\n")
    (repo / "zettelkasten/_system/state/s.md").write_text("state\n")

    result = _run_script(repo, "finalize-tick.sh", "scheduler/process")
    assert result.returncode == 0, result.stderr

    log = _git(repo, "log", "--oneline", "origin/main..HEAD")
    assert log.stdout.strip() == "", "all commits should be pushed (no ahead)"

    head = _git(repo, "log", "--oneline", "-2")
    subjects = [line.split(" ", 1)[1] for line in head.stdout.strip().splitlines()]
    assert subjects[0].startswith("scheduler/process:")
    assert subjects[0].endswith("[scheduled]")
    assert "record(s)" in subjects[0]


def test_engine_paths_not_committed(repo: Path) -> None:
    (repo / "zettelkasten/_records/r1.md").write_text("owner data\n")
    (repo / "scripts" / "drift.sh").write_text("# engine drift\n")
    (repo / "integrations").mkdir(exist_ok=True)
    (repo / "integrations" / "drift.md").write_text("# more drift\n")

    result = _run_script(repo, "finalize-tick.sh", "scheduler/process")
    assert result.returncode == 0, result.stderr

    head_files = _git(repo, "show", "--name-only", "--format=", "HEAD")
    assert "zettelkasten/_records/r1.md" in head_files.stdout
    assert "scripts/drift.sh" not in head_files.stdout
    assert "integrations/drift.md" not in head_files.stdout

    clar = repo / "zettelkasten/_system/state/CLARIFICATIONS.md"
    assert clar.exists()
    assert "engine drift" in clar.read_text()


def test_stage_is_idempotent(repo: Path) -> None:
    (repo / "zettelkasten/_records/r1.md").write_text("rec1\n")

    r1 = _run_script(repo, "stage.sh")
    r2 = _run_script(repo, "stage.sh")
    r3 = _run_script(repo, "stage.sh")
    assert r1.returncode == 0
    assert r2.returncode == 0
    assert r3.returncode == 0

    staged = _git(repo, "diff", "--cached", "--name-only")
    assert "zettelkasten/_records/r1.md" in staged.stdout
    assert len(staged.stdout.strip().splitlines()) == 1


def test_fold_recovery_collapses_previous_scheduled_commits(repo: Path) -> None:
    (repo / "zettelkasten/_records/x.md").write_text("x\n")
    _git(repo, "add", "zettelkasten/_records/x.md")
    _git(repo, "commit", "-q", "-m", "scheduler/process: partial1 [scheduled]")
    (repo / "zettelkasten/_records/y.md").write_text("y\n")
    _git(repo, "add", "zettelkasten/_records/y.md")
    _git(repo, "commit", "-q", "-m", "scheduler/process: partial2 [scheduled]")

    ahead_before = _git(repo, "rev-list", "--count", "origin/main..HEAD")
    assert ahead_before.stdout.strip() == "2"

    (repo / "zettelkasten/_records/z.md").write_text("z\n")
    result = _run_script(repo, "finalize-tick.sh", "scheduler/lint")
    assert result.returncode == 0, result.stderr
    assert "folding 2 previous unpushed" in result.stdout

    ahead_after = _git(repo, "rev-list", "--count", "origin/main..HEAD")
    assert ahead_after.stdout.strip() == "0", "all folded commits pushed"

    new_commits_locally = _git(repo, "log", "--oneline", "HEAD~1..HEAD")
    assert new_commits_locally.stdout.count("\n") == 1, "single new commit"

    head_files = _git(repo, "show", "--name-only", "--format=", "HEAD")
    for fname in ("x.md", "y.md", "z.md"):
        assert fname in head_files.stdout


def test_refuses_to_reset_over_owner_manual_commit(repo: Path) -> None:
    (repo / "zettelkasten/_records/manual.md").write_text("owner work\n")
    _git(repo, "add", "zettelkasten/_records/manual.md")
    _git(repo, "commit", "-q", "-m", "owner manual edit")

    (repo / "zettelkasten/_records/dirty.md").write_text("d\n")
    result = _run_script(repo, "finalize-tick.sh", "scheduler/process")
    assert result.returncode == 2
    assert "refusing to reset" in result.stderr

    log = _git(repo, "log", "--oneline", "-2")
    assert "owner manual edit" in log.stdout
    assert "[scheduled]" not in log.stdout


def test_nothing_to_commit_is_noop(repo: Path) -> None:
    result = _run_script(repo, "finalize-tick.sh", "scheduler/lint")
    assert result.returncode == 0
    assert "nothing to commit" in result.stdout


def test_ship_failure_note_falls_back_to_local_when_finalize_refuses(repo: Path) -> None:
    (repo / "zettelkasten/_records/manual.md").write_text("owner work\n")
    _git(repo, "add", "zettelkasten/_records/manual.md")
    _git(repo, "commit", "-q", "-m", "owner manual edit")

    result = _run_script(
        repo,
        "ship-failure-note.sh",
        "test cause",
        "process-scheduled",
    )
    assert result.returncode == 0, result.stderr
    assert "falling back to local-only commit" in result.stderr
    assert "committed locally" in result.stdout

    clar_text = (repo / "zettelkasten/_system/state/CLARIFICATIONS.md").read_text()
    assert "test cause" in clar_text
    assert "process-scheduled" in clar_text

    head_subject = _git(repo, "log", "-1", "--format=%s").stdout.strip()
    assert head_subject.startswith("scheduler/failure-local:")

    ahead = _git(repo, "rev-list", "--count", "origin/main..HEAD").stdout.strip()
    assert ahead == "2", "owner commit + local failure note both unpushed"


def test_message_heuristic_records_only(repo: Path) -> None:
    for i in range(3):
        (repo / f"zettelkasten/_records/r{i}.md").write_text(f"{i}\n")

    result = _run_script(repo, "finalize-tick.sh", "scheduler/process")
    assert result.returncode == 0

    subject = _git(repo, "log", "-1", "--format=%s").stdout.strip()
    assert subject == "scheduler/process: 3 record(s) updated [scheduled]"


FAKE_GH_SCRIPT = r"""#!/usr/bin/env bash
# Fake gh CLI for tests. Honours FAKE_GH_BARE (path to bare origin repo)
# and FAKE_GH_STATE_DIR (per-test marker dir).
set -u
state_dir="${FAKE_GH_STATE_DIR:-/tmp/fake-gh-state}"
mkdir -p "$state_dir"
bare="${FAKE_GH_BARE:-}"

slug() { printf '%s' "$1" | tr '/' '_'; }

case "$1" in
  repo)
    if [ "$2" = "view" ]; then
      echo "test-owner/test-repo"
      exit 0
    fi
    ;;
  pr)
    sub="$2"; shift 2
    case "$sub" in
      list)
        head=""
        while [ $# -gt 0 ]; do
          if [ "$1" = "--head" ]; then head="$2"; shift 2; continue; fi
          shift
        done
        marker="$state_dir/pr-$(slug "$head")"
        if [ -f "$marker" ]; then
          cat "$marker"
        fi
        exit 0
        ;;
      create)
        head=""; title=""
        while [ $# -gt 0 ]; do
          case "$1" in
            --head) head="$2"; shift 2 ;;
            --title) title="$2"; shift 2 ;;
            *) shift ;;
          esac
        done
        pr_num=$((42 + RANDOM % 1000))
        slug_head="$(slug "$head")"
        echo "$pr_num" > "$state_dir/pr-$slug_head"
        echo "$head" > "$state_dir/pr-$slug_head.branch"
        echo "$title" > "$state_dir/pr-$slug_head.title"
        echo "https://github.com/test-owner/test-repo/pull/$pr_num"
        exit 0
        ;;
      merge)
        pr="$1"; shift 1
        delete=0
        while [ $# -gt 0 ]; do
          case "$1" in
            --delete-branch) delete=1; shift ;;
            *) shift ;;
          esac
        done
        for f in "$state_dir"/pr-*; do
          [ -f "$f" ] || continue
          case "$f" in *.branch|*.title|*.state) continue ;; esac
          stored="$(cat "$f")"
          if [ "$stored" = "$pr" ]; then
            slug_head="$(basename "$f")"
            slug_head="${slug_head#pr-}"
            branch="$(cat "$state_dir/pr-$slug_head.branch")"
            if [ -n "$bare" ]; then
              GIT_DIR="$bare" git update-ref refs/heads/main "refs/heads/$branch" || exit 1
              if [ "$delete" -eq 1 ]; then
                GIT_DIR="$bare" git update-ref -d "refs/heads/$branch" || true
              fi
              echo "MERGED" > "$state_dir/pr-$pr.state"
              exit 0
            fi
            exit 0
          fi
        done
        echo "fake-gh: PR $pr not found" >&2
        exit 1
        ;;
      view)
        pr="$1"; shift 1
        if [ -f "$state_dir/pr-$pr.state" ]; then
          cat "$state_dir/pr-$pr.state"
        else
          echo "OPEN"
        fi
        exit 0
        ;;
    esac
    ;;
  api)
    method=""; endpoint=""
    while [ $# -gt 0 ]; do
      case "$1" in
        -X|--method) method="$2"; shift 2 ;;
        repos/*) endpoint="$1"; shift ;;
        *) shift ;;
      esac
    done
    if [ "${method:-}" = "DELETE" ] && [ -n "$bare" ]; then
      branch="${endpoint##*/heads/}"
      GIT_DIR="$bare" git update-ref -d "refs/heads/$branch" 2>/dev/null || true
      exit 0
    fi
    exit 0
    ;;
esac
echo "fake-gh: unknown command: $*" >&2
exit 1
"""


def _install_fake_gh(tmp_path: Path, bare_origin: Path) -> tuple[Path, dict]:
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(exist_ok=True)
    state_dir = tmp_path / "fake-gh-state"
    state_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH_SCRIPT)
    gh.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_GH_BARE": str(bare_origin),
        "FAKE_GH_STATE_DIR": str(state_dir),
    }
    return bin_dir, env


def test_routines_mode_push_to_sandbox_and_pr_merge(tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    work.mkdir()

    _git(work, "init", "-q", "-b", "main")
    _git(work, "remote", "add", "origin", str(origin))
    scheduler_dst = work / "scripts" / "scheduler"
    scheduler_dst.mkdir(parents=True)
    for name in ("stage.sh", "finalize-tick.sh", "_classify_paths.py"):
        shutil.copy(SCHEDULER_DIR / name, scheduler_dst / name)
    shutil.copy(MANIFEST, work / ".engine-manifest.yml")
    (work / "zettelkasten/_records").mkdir(parents=True)
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "initial")
    _git(work, "push", "-q", "-u", "origin", "main")

    state_dir = work / ".scheduler-state"
    state_dir.mkdir()
    (state_dir / "start-branch").write_text("claude/test-sandbox-XYZ\n")

    _, gh_env = _install_fake_gh(tmp_path, origin)

    (work / "zettelkasten/_records/r1.md").write_text("rec1\n")
    (work / "zettelkasten/_records/r2.md").write_text("rec2\n")

    result = subprocess.run(
        ["bash", "scripts/scheduler/finalize-tick.sh", "scheduler/process"],
        cwd=work,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            **gh_env,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "ROUTINES mode" in result.stdout
    assert "PR #" in result.stdout
    assert "squash-merged" in result.stdout

    refs = subprocess.run(
        ["git", "ls-remote", "--heads", str(origin)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "claude/test-sandbox-XYZ" not in refs.stdout, "sandbox branch must be deleted"
    assert "refs/heads/main" in refs.stdout, "main must exist"

    main_log = subprocess.run(
        ["git", "log", "--format=%s", "-1", "main"],
        cwd=origin,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "scheduler/process:" in main_log.stdout
    assert "[scheduled]" in main_log.stdout


def test_routines_mode_gh_missing_fails_gracefully(tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "remote", "add", "origin", str(origin))
    scheduler_dst = work / "scripts" / "scheduler"
    scheduler_dst.mkdir(parents=True)
    for name in ("stage.sh", "finalize-tick.sh", "_classify_paths.py"):
        shutil.copy(SCHEDULER_DIR / name, scheduler_dst / name)
    shutil.copy(MANIFEST, work / ".engine-manifest.yml")
    (work / "zettelkasten/_records").mkdir(parents=True)
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "initial")
    _git(work, "push", "-q", "-u", "origin", "main")

    state_dir = work / ".scheduler-state"
    state_dir.mkdir()
    (state_dir / "start-branch").write_text("claude/no-gh-XYZ\n")

    (work / "zettelkasten/_records/r1.md").write_text("rec1\n")

    # Build a PATH that genuinely lacks `gh`: on GitHub runners gh lives in
    # /usr/bin, so just dropping homebrew dirs is not enough. Symlink every
    # system tool except gh into a sandbox dir and use it as the sole PATH.
    sandbox_bin = tmp_path / "sandbox-bin"
    sandbox_bin.mkdir()
    for bin_dir in ("/usr/bin", "/bin"):
        for tool in Path(bin_dir).iterdir():
            if tool.name == "gh":
                continue
            try:
                (sandbox_bin / tool.name).symlink_to(tool)
            except FileExistsError:
                pass  # same tool present in both dirs
    minimal_path = str(sandbox_bin)

    result = subprocess.run(
        ["bash", "scripts/scheduler/finalize-tick.sh", "scheduler/process"],
        cwd=work,
        capture_output=True,
        text=True,
        env={
            "PATH": minimal_path,
            "HOME": str(tmp_path),
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )
    assert result.returncode == 2
    assert "gh CLI not found" in result.stderr
    local_head = _git(work, "log", "--format=%s", "-1").stdout.strip()
    assert "scheduler/process:" in local_head



def test_classifier_uses_manifest(tmp_path: Path) -> None:
    paths = "\n".join([
        "zettelkasten/_records/x.md",
        "scripts/scheduler/stage.sh",
        ".engine-manifest.yml",
        "zettelkasten/_system/state/s.md",
        "zettelkasten/_system/docs/SYSTEM_CONFIG.md",
        "some/random/path/AUDIENCES.template.md",
    ])
    result = subprocess.run(
        ["python3", str(SCHEDULER_DIR / "_classify_paths.py")],
        input=paths,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    got: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        label, path = line.split("\t", 1)
        got[path] = label
    assert got == {
        "zettelkasten/_records/x.md": "OWNER",
        "scripts/scheduler/stage.sh": "ENGINE",
        ".engine-manifest.yml": "ENGINE",
        "zettelkasten/_system/state/s.md": "OWNER",
        "zettelkasten/_system/docs/SYSTEM_CONFIG.md": "ENGINE",
        "some/random/path/AUDIENCES.template.md": "ENGINE",
    }
