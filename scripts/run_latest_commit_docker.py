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


ROOT = Path(__file__).resolve().parents[1]
IMAGE_NAME = "tms-automation"
COMPOSE_IMAGE_TAG = "all-in-one"
SOURCE_LABEL = "org.opencontainers.image.source-version"
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


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    printable = " ".join(command)
    print(f"\n$ {printable}", flush=True)
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
        text=True,
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


def ensure_required_tools() -> None:
    for command in (["git", "--version"], ["docker", "--version"]):
        try:
            subprocess.check_output(command, text=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise SystemExit(f"Required command not found or not working: {command[0]}") from exc
    docker_compose_command()


def current_commit() -> str:
    return capture(["git", "rev-parse", "--short=12", "HEAD"], check=False) or "unknown"


def current_branch() -> str:
    return capture(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=False) or "unknown"


def dirty_status() -> str:
    return capture(["git", "status", "--short"], check=False)


def should_include(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    if relative.parts[:1] == ("data",) and path.suffix == ".csv":
        return False
    return path.is_file()


def source_files() -> list[Path]:
    return sorted(path for path in ROOT.rglob("*") if should_include(path))


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
        help="Run git pull --ff-only before checking the current files.",
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
    args = parser.parse_args()

    ensure_required_tools()
    compose = docker_compose_command()

    if args.pull_git:
        branch = current_branch()
        if branch == "HEAD":
            raise SystemExit("--pull-git cannot run from detached HEAD.")
        if dirty_status():
            print("Working tree has local changes; skipping git pull to avoid overwriting them.")
        else:
            run(["git", "pull", "--ff-only"])

    commit = current_commit()
    fingerprint = source_fingerprint()
    source_id = f"{commit}-{fingerprint}"
    compose_tag = f"{IMAGE_NAME}:{COMPOSE_IMAGE_TAG}"
    build_date = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    existing_source = image_label(compose_tag, SOURCE_LABEL)
    build_needed = args.force_build or args.no_cache or existing_source != source_id

    print("\nSource context:")
    print(f"  commit:      {commit}")
    print(f"  fingerprint: {fingerprint}")
    print(f"  source id:   {source_id}")
    if dirty_status():
        print("  mode:        current files include uncommitted changes")
    else:
        print("  mode:        clean commit checkout")

    if build_needed:
        sys.stdout.flush()
        build_command = [
            "docker",
            "build",
            "--build-arg",
            f"GIT_COMMIT={commit}",
            "--build-arg",
            f"SOURCE_VERSION={source_id}",
            "--build-arg",
            f"BUILD_DATE={build_date}",
            "-t",
            compose_tag,
        ]
        if args.no_cache:
            build_command.append("--no-cache")
        build_command.append(str(ROOT))
        run(build_command)
    else:
        print(f"\nImage {compose_tag} already matches current files; skipping build.")

    if image_exists(compose_tag):
        print("\nAvailable image tags:")
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
            cleanup_old_app_images({compose_tag})
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
