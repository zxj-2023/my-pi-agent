#!/usr/bin/env python3
"""Automated cross-platform distribution packager for my-pi-agent.

This script compiles the TUI frontend, bundles the Python core engine,
and generates portable standalone release packages (.zip and .tar.gz).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


def get_version_from_pyproject(pyproject_path: Path) -> str:
    """Extract project version from pyproject.toml."""
    content = pyproject_path.read_text(encoding="utf-8")
    match = re.search(r'version\s*=\s*"([^"]+)"', content)
    if not match:
        raise ValueError(f"Could not parse version from {pyproject_path}")
    return match.group(1)


def generate_launcher_scripts(dest_dir: Path) -> tuple[Path, Path]:
    """Generate Windows .cmd and POSIX sh launcher scripts."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    cmd_file = dest_dir / "my-pi-agent.cmd"
    cmd_file.write_text(
        '@echo off\r\nsetlocal\r\nnode "%~dp0tui\\bin\\my-agent.js" %*\r\n',
        encoding="utf-8",
    )

    sh_file = dest_dir / "my-pi-agent"
    sh_file.write_text(
        '#!/usr/bin/env sh\nDIR="$(cd "$(dirname "$0")" && pwd)"\nexec node "$DIR/tui/bin/my-agent.js" "$@"\n',
        encoding="utf-8",
    )
    try:
        sh_file.chmod(0o755)
    except Exception:
        pass

    return cmd_file, sh_file


def build_tui(repo_root: Path) -> None:
    """Build the TypeScript TUI presentation layer."""
    print("[1/4] 构建 TypeScript TUI 前端...")
    npm_cmd = shutil.which("npm")
    if not npm_cmd:
        raise RuntimeError("未在当前系统 PATH 中找到 npm，无法编译 TUI。")
    subprocess.run([npm_cmd, "run", "build", "--prefix", "tui"], cwd=repo_root, check=True)


def assemble_portable_package(repo_root: Path, dist_dir: Path, version: str) -> Path:
    """Assemble all runtime assets into a clean staging directory."""
    print("[2/4] 收集运行时资产与依赖...")
    pkg_name = f"my-pi-agent-v{version}-portable"
    staging_dir = dist_dir / pkg_name
    if staging_dir.exists():
        try:
            shutil.rmtree(staging_dir)
        except OSError:
            pass
    staging_dir.mkdir(parents=True, exist_ok=True)

    # 1. 拷贝 Python 源码
    shutil.copytree(repo_root / "src", staging_dir / "src")

    # 2. 拷贝编译后的 TUI 产物
    (staging_dir / "tui").mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / "tui" / "dist", staging_dir / "tui" / "dist")
    shutil.copytree(repo_root / "tui" / "bin", staging_dir / "tui" / "bin")
    shutil.copy2(repo_root / "tui" / "package.json", staging_dir / "tui" / "package.json")

    # 3. 拷贝元数据与说明文档
    shutil.copy2(repo_root / "pyproject.toml", staging_dir / "pyproject.toml")
    if (repo_root / "README.md").exists():
        shutil.copy2(repo_root / "README.md", staging_dir / "README.md")
    if (repo_root / "LICENSE").exists():
        shutil.copy2(repo_root / "LICENSE", staging_dir / "LICENSE")

    # 4. 生成跨平台启动脚本
    generate_launcher_scripts(staging_dir)

    return staging_dir


def create_archives(staging_dir: Path, dist_dir: Path, version: str) -> tuple[Path, Path]:
    """Compress staging directory into .zip and .tar.gz archives."""
    print("[3/4] 压缩生成发布归档包...")
    base_name = f"my-pi-agent-v{version}-portable"

    # Zip 压缩包
    zip_path = dist_dir / f"{base_name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in staging_dir.rglob("*"):
            if file.is_file():
                arcname = file.relative_to(dist_dir)
                zf.write(file, arcname)

    # Tar.gz 压缩包
    tar_path = dist_dir / f"{base_name}.tar.gz"
    if tar_path.exists():
        tar_path.unlink()
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(staging_dir, arcname=base_name)

    return zip_path, tar_path


def main() -> int:
    """CLI orchestrator for building distributions."""
    parser = argparse.ArgumentParser(description="Build portable distributions for my-pi-agent")
    parser.add_argument("--skip-build-tui", action="store_true", help="Skip npm run build step")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    dist_dir = repo_root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    version = get_version_from_pyproject(repo_root / "pyproject.toml")
    print(f"=== 开始打包 my-pi-agent v{version} ===")

    if not args.skip_build_tui:
        build_tui(repo_root)

    staging_dir = assemble_portable_package(repo_root, dist_dir, version)
    zip_path, tar_path = create_archives(staging_dir, dist_dir, version)

    print("[4/4] 打包完成！")
    print(f"  - 便携目录: {staging_dir}")
    print(f"  - Zip 归档: {zip_path} ({zip_path.stat().st_size / 1024:.1f} KB)")
    print(f"  - Tar 归档: {tar_path} ({tar_path.stat().st_size / 1024:.1f} KB)")
    print("========================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
