"""Create or update the public Hugging Face Docker Space.

The access token is read only from HF_TOKEN. It is never accepted as a command
line argument so it is less likely to be saved in shell history or CI logs.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile


SPACE_ID = "henryleeeee/atommovr-ui-zh"
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
APP_FILES = (
    "app.py",
    "benchmark.py",
    "comparison.py",
    "scheduling.py",
    "simulator.py",
    "version.py",
    "player.css",
    "player.html",
    "player.js",
    "requirements.txt",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "算法说明.md",
)
SPACE_FILES = ("Dockerfile", "README.md")


def stage_bundle(destination: Path) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for relative in APP_FILES:
        source = PROJECT_ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(f"缺少在线运行文件：{source}")
        shutil.copy2(source, destination / relative)
        copied.append(relative)
    for relative in SPACE_FILES:
        source = HERE / relative
        if not source.is_file():
            raise FileNotFoundError(f"缺少 Space 配置文件：{source}")
        shutil.copy2(source, destination / relative)
        copied.append(relative)
    return sorted(copied)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="部署中文 atommovr UI 到公开 Hugging Face Space")
    parser.add_argument("--dry-run", action="store_true", help="只检查并组装部署文件，不连接 Hugging Face")
    parser.add_argument("--output", type=Path, help="dry-run 时将部署文件保留在指定目录")
    options = parser.parse_args(argv)

    if options.output and not options.dry_run:
        parser.error("--output 只能与 --dry-run 一起使用")

    if options.dry_run and options.output:
        copied = stage_bundle(options.output.resolve())
        print(f"部署包检查通过：{options.output.resolve()}（{len(copied)} 个文件）")
        return 0

    with tempfile.TemporaryDirectory(prefix="atommovr-space-") as temporary:
        bundle = Path(temporary)
        copied = stage_bundle(bundle)
        if options.dry_run:
            print(f"部署包检查通过（{len(copied)} 个文件）：" + "、".join(copied))
            return 0

        token = os.environ.get("HF_TOKEN", "").strip()
        if not token:
            print(
                "缺少 HF_TOKEN。请把具有 Space 写入权限的令牌保存为 GitHub Actions secret；"
                "不要把令牌写入代码、日志或聊天。",
                file=sys.stderr,
            )
            return 2

        from huggingface_hub import HfApi

        api = HfApi(token=token)
        api.create_repo(
            repo_id=SPACE_ID,
            repo_type="space",
            space_sdk="docker",
            private=False,
            exist_ok=True,
        )
        commit = api.upload_folder(
            repo_id=SPACE_ID,
            repo_type="space",
            folder_path=bundle,
            delete_patterns="*",
            commit_message="Deploy Chinese public interface",
        )
        print(f"Space 已更新：https://huggingface.co/spaces/{SPACE_ID}")
        print(f"部署提交：{commit.oid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
