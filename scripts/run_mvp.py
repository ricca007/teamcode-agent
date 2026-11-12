"""一条命令准备本地商城并启动完整 MVP；不修改 A/B 源码。"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(data_dir: Path):
    repo = data_dir / "shop"
    data_dir.mkdir(parents=True, exist_ok=True)
    if not repo.exists():
        shutil.copytree(ROOT / "examples" / "shop", repo)
        for args in [
            ["init", "-b", "main"],
            ["add", "."],
            ["commit", "-m", "classroom shop"],
        ]:
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=TeamCode MVP",
                    "-c",
                    "user.email=mvp@example.invalid",
                    *args,
                ],
                cwd=repo,
                check=True,
                capture_output=True,
            )
    return repo


def main():
    parser = argparse.ArgumentParser(description="启动 TeamCode 课堂 MVP")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".mvp")
    parser.add_argument("--build", action="store_true", help="启动前重建前端")
    args = parser.parse_args()
    from dotenv import load_dotenv

    load_dotenv(ROOT / "mvp.env")
    repo = prepare(args.data_dir.resolve())
    if args.build or not (ROOT / "frontend" / "dist" / "index.html").exists():
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if not npm:
            raise SystemExit("未找到 npm；请安装 Node.js 并在 frontend 执行 npm ci")
        subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
    os.environ.setdefault(
        "DATABASE_URL", f"sqlite+aiosqlite:///{args.data_dir.resolve() / 'mvp.db'}"
    )
    os.environ["TEAMCODE_DEMO"] = "1"
    os.environ["TEAMCODE_DEMO_REPO"] = str(repo)
    os.environ["TEAMCODE_REQUIRE_AUTH"] = "1"
    os.environ.setdefault("TEAMCODE_MOCK_DELAY", "0.4")
    sys.path.insert(0, str(ROOT / "backend"))
    import uvicorn

    print(f"MVP: http://127.0.0.1:{args.port} | Shop: {repo}", flush=True)
    uvicorn.run("app.main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
