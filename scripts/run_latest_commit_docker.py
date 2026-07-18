#!/usr/bin/env python3
"""Build and run Docker from the current files on disk.

Works on Windows and macOS/Linux as long as Git, Docker, and Docker Compose are
available on PATH. The script is intentionally workspace-aware: uncommitted
changes are included in the image fingerprint, so it runs what you have now,
not only the latest commit.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import IO


ROOT = Path(__file__).resolve().parents[1]
IMAGE_NAME = "tms-automation"
COMPOSE_IMAGE_TAG = "all-in-one"
DEPS_IMAGE_TAG = "python-deps"
SOURCE_LABEL = "org.opencontainers.image.source-version"
DEPS_VERSION_LABEL = "org.opencontainers.image.deps-version"
PRIMARY_BRANCH = os.environ.get("TMS_PRIMARY_BRANCH", "codex/backtesting")
RUN_LOCK_FILE = Path(
    os.environ.get("TMS_RUN_LOCK_FILE", str(ROOT / ".git" / "tms-latest-commit.lock"))
)
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    "build",
}
EXCLUDED_SUFFIXES = {".pyc", ".zip"}

# Only hash files that affect the Docker image. Doc/test-only edits should not force rebuilds.
DOCKER_FINGERPRINT_PREFIXES = (
    "Dockerfile",
    ".dockerignore",
    "docker-compose.yml",
    "docker-entrypoint-all-in-one.sh",
    "nginx-tms-automation.conf",
    "requirements.txt",
    "requirements-heavy.txt",
    "main.py",
    "database.py",
    "websocket.py",
    "models/",
    "schemas/",
    "utils/",
    "services/",
    "config/",
    "exceptions/",
    "initialize_project/",
    "alembic/",
    "scripts/init_local_db.py",
    "scripts/show-public-url.sh",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/tsconfig.json",
    "frontend/public/",
    "frontend/src/",
)


def run(command: list[str], *, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    printable = " ".join(command)
    print(f"\n$ {printable}", flush=True)
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
        text=True,
        env=env,
    )


def capture(command: list[str], *, check: bool = True) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.stdout.strip()


def docker_compose_command() -> list[str]:
    try:
        subprocess.check_output(["docker", "compose", "version"], text=True)
        return ["docker", "compose"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        subprocess.check_output(["docker-compose", "version"], text=True)
        return ["docker-compose"]


def ensure_docker_daemon() -> None:
    result = subprocess.run(
        ["docker", "info"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode == 0:
        return
    stderr = (result.stderr or "").lower()
    if "cannot connect" in stderr or "dockerdesktoplinuxengine" in stderr:
        raise SystemExit(
            "Docker is installed but the Docker Desktop engine is not running.\n"
            "Start Docker Desktop from the Start menu, wait until it shows "
            "'Docker Desktop is running', then run this script again."
        )
    raise SystemExit(f"Docker is not available: {result.stderr.strip() or 'docker info failed'}")


def ensure_required_tools() -> None:
    for command in (["git", "--version"], ["docker", "--version"]):
        try:
            subprocess.check_output(command, text=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise SystemExit(f"Required command not found or not working: {command[0]}") from exc
    ensure_docker_daemon()
    docker_compose_command()


def current_commit() -> str:
    return capture(["git", "rev-parse", "--short=12", "HEAD"], check=False) or "unknown"


def current_branch() -> str:
    return capture(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=False) or "unknown"


def dirty_status() -> str:
    return capture(["git", "status", "--short"], check=False)


def acquire_run_lock() -> IO[str] | None:
    """Prevent overlapping cron/manual runs from rebuilding the same app."""
    RUN_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    handle = RUN_LOCK_FILE.open("a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if not handle.read(1):
                handle.seek(0)
                handle.write("1")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        handle.close()
        print(f"Another latest-commit Docker run already holds {RUN_LOCK_FILE}; skipping.")
        return None
    return handle


def ensure_primary_branch(branch: str) -> None:
    """Switch to the configured branch, including from a fresh main checkout."""
    current = current_branch()
    if current == branch:
        print(f"Primary branch: {branch}")
        return
    if current == "HEAD":
        raise SystemExit(f"Cannot switch a detached HEAD to primary branch {branch!r}.")
    if dirty_status():
        raise SystemExit(
            f"This runner uses primary branch {branch!r}, but the current branch is {current!r} "
            "and has local changes. Commit or move those changes before running it."
        )
    local_exists = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=ROOT,
    ).returncode == 0
    if local_exists:
        run(["git", "switch", branch])
    else:
        print(f"Primary branch {branch!r} is not local; fetching it from origin.")
        run(["git", "fetch", "origin", f"{branch}:refs/remotes/origin/{branch}"])
        remote_exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], cwd=ROOT,
        ).returncode == 0
        if not remote_exists:
            raise SystemExit(f"Primary branch {branch!r} was not found on origin.")
        run(["git", "switch", "--track", "-c", branch, f"origin/{branch}"])
    print(f"Primary branch: {branch}")


def fast_forward_from_origin(branch: str) -> None:
    """Fetch and fast-forward the exact configured branch without relying on upstream config."""
    remote_ref = f"refs/remotes/origin/{branch}"
    # Use the remote's configured fetch map. Combining --prune with a custom
    # remote-tracking refspec can prune that same ref on some Git versions.
    run(["git", "fetch", "--prune", "origin"])
    remote_exists = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", remote_ref], cwd=ROOT,
    ).returncode == 0
    if not remote_exists:
        raise SystemExit(f"Primary branch {branch!r} was not found on origin.")
    run(["git", "merge", "--ff-only", remote_ref])


def should_include(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    if relative.parts[:1] == ("data",) and path.suffix == ".csv":
        return False
    return path.is_file()


def affects_docker_image(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    for prefix in DOCKER_FINGERPRINT_PREFIXES:
        if relative == prefix or relative.startswith(prefix):
            return should_include(path)
    return False


def source_files() -> list[Path]:
    return sorted(path for path in ROOT.rglob("*") if affects_docker_image(path))


def source_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in source_files():
        relative = path.relative_to(ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def deps_fingerprint() -> str:
    digest = hashlib.sha256()
    for name in ("requirements-heavy.txt", "requirements.txt", "Dockerfile"):
        path = ROOT / name
        if not path.is_file():
            continue
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def image_label(image: str, label: str) -> str:
    output = capture(
        ["docker", "image", "inspect", image, "--format", f"{{{{ index .Config.Labels \"{label}\" }}}}"],
        check=False,
    )
    return output if output != "<no value>" else ""


def running_container_image() -> str:
    return capture(
        ["docker", "inspect", "tms-automation", "--format", "{{.Image}}"],
        check=False,
    )


def container_exists(name: str) -> bool:
    return subprocess.run(
        ["docker", "container", "inspect", name],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    ).returncode == 0


def remove_container_preserving_volumes(name: str) -> None:
    run(["docker", "stop", name], check=False)
    run(["docker", "rm", name])


def image_exists(image: str) -> bool:
    return subprocess.run(
        ["docker", "image", "inspect", image],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    ).returncode == 0


def image_tags(repository: str) -> list[str]:
    output = capture(
        ["docker", "image", "ls", repository, "--format", "{{.Repository}}:{{.Tag}}"],
        check=False,
    )
    return [
        line.strip()
        for line in output.splitlines()
        if line.strip() and not line.strip().endswith(":<none>")
    ]


def cleanup_old_app_images(keep_tags: set[str]) -> None:
    old_tags = sorted(tag for tag in image_tags(IMAGE_NAME) if tag not in keep_tags)
    if not old_tags:
        print("\nNo old tms-automation image tags to remove.")
        return

    print("\nRemoving old tms-automation image tags after successful startup.")
    for tag in old_tags:
        run(["docker", "image", "rm", tag], check=False)
    run(["docker", "image", "prune", "-f"], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and run Docker from the current files on disk.",
    )
    parser.add_argument(
        "--pull-git",
        action="store_true",
        help="Fetch and fast-forward the selected branch before building.",
    )
    parser.add_argument(
        "--branch",
        default=PRIMARY_BRANCH,
        help=f"Primary branch to build (default: {PRIMARY_BRANCH}).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Build without Docker layer cache.",
    )
    parser.add_argument(
        "--force-build",
        action="store_true",
        help="Build even if an image with the same source fingerprint already exists.",
    )
    parser.add_argument(
        "--force-recreate",
        action="store_true",
        help="Recreate the compose container even if it already uses the matching image.",
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="Only build/tag the image when needed; do not restart docker compose.",
    )
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="Fail instead of deploying when the selected branch has local changes.",
    )
    args = parser.parse_args()

    run_lock = acquire_run_lock()
    if run_lock is None:
        return 0

    ensure_required_tools()
    compose = docker_compose_command()
    ensure_primary_branch(args.branch)

    if args.pull_git:
        branch = current_branch()
        if branch == "HEAD":
            raise SystemExit("--pull-git cannot run from detached HEAD.")
        changes = dirty_status()
        if changes and args.require_clean:
            raise SystemExit(
                "Scheduled latest-commit run requires a clean working tree; refusing to deploy "
                "uncommitted server files.\n" + changes
            )
        if changes:
            print("Working tree has local changes; skipping remote update to avoid overwriting them.")
        else:
            fast_forward_from_origin(args.branch)

    commit = current_commit()
    fingerprint = source_fingerprint()
    source_id = f"{commit}-{fingerprint}"
    deps_id = deps_fingerprint()
    compose_tag = f"{IMAGE_NAME}:{COMPOSE_IMAGE_TAG}"
    deps_tag = f"{IMAGE_NAME}:{DEPS_IMAGE_TAG}"
    build_date = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    existing_source = image_label(compose_tag, SOURCE_LABEL)
    existing_deps = image_label(deps_tag, DEPS_VERSION_LABEL)
    build_needed = args.force_build or args.no_cache or existing_source != source_id
    deps_build_needed = args.force_build or args.no_cache or existing_deps != deps_id

    print("\nSource context:")
    print(f"  commit:      {commit}")
    print(f"  fingerprint: {fingerprint}")
    print(f"  source id:   {source_id}")
    print(f"  deps id:     {deps_id}")
    if dirty_status():
        print("  mode:        current files include uncommitted changes")
    else:
        print("  mode:        clean commit checkout")

    if build_needed or deps_build_needed:
        sys.stdout.flush()
        build_env = os.environ.copy()
        build_env.setdefault("DOCKER_BUILDKIT", "1")

        if deps_build_needed:
            print(f"\nBuilding Python deps image ({deps_tag})...")
            deps_command = [
                "docker",
                "build",
                "--target",
                "python-deps",
                "--build-arg",
                f"DEPS_VERSION={deps_id}",
                "-t",
                deps_tag,
            ]
            if image_exists(deps_tag) and not args.no_cache:
                deps_command.extend(["--cache-from", deps_tag])
            if args.no_cache:
                deps_command.append("--no-cache")
            deps_command.append(str(ROOT))
            run(deps_command, env=build_env)
        else:
            print(f"\nPython deps image {deps_tag} already matches; skipping deps build.")

        if build_needed:
            print(f"\nBuilding application image ({compose_tag})...")
            build_command = [
                "docker",
                "build",
                "--build-arg",
                f"GIT_COMMIT={commit}",
                "--build-arg",
                f"SOURCE_VERSION={source_id}",
                "--build-arg",
                f"BUILD_DATE={build_date}",
                "--build-arg",
                f"DEPS_VERSION={deps_id}",
                "-t",
                compose_tag,
            ]
            if image_exists(deps_tag) and not args.no_cache:
                build_command.extend(["--cache-from", deps_tag])
            if args.no_cache:
                build_command.append("--no-cache")
            build_command.append(str(ROOT))
            run(build_command, env=build_env)
        else:
            print(f"\nImage {compose_tag} already matches current files; skipping app build.")
    else:
        print(f"\nImages already match current files; skipping build.")

    if image_exists(compose_tag) or image_exists(deps_tag):
        print("\nAvailable image tags:")
        if image_exists(deps_tag):
            print(f"  {deps_tag}")
        if image_exists(compose_tag):
            print(f"  {compose_tag}")

    if not args.no_run:
        running_image = running_container_image()
        running_source = image_label(running_image, SOURCE_LABEL) if running_image else ""
        recreate = args.force_recreate or build_needed or running_source != source_id
        if recreate:
            sys.stdout.flush()
            if container_exists("tms-automation"):
                print("\nRemoving old tms-automation container after successful image build.")
                print("Database volume is preserved; not removing Docker volumes.")
                remove_container_preserving_volumes("tms-automation")
            run([*compose, "up", "-d", "--no-build", "--force-recreate"])
            cleanup_old_app_images({compose_tag, deps_tag})
        else:
            print("\nContainer already runs the matching source image; leaving it running.")
        print("\nApp:")
        print("  http://localhost:3000")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
        raise SystemExit(130)
