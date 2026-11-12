"""teamcode pull-interfaces --project p_demo --api-key TOKEN --output interfaces.md"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def fetch(path, *, base=None, token=None):
    request = Request(
        (base or os.getenv("TEAMCODE_API_BASE", "http://127.0.0.1:8000")).rstrip("/")
        + path,
        headers={
            "Authorization": "Bearer " + (token or os.getenv("TEAMCODE_TOKEN", ""))
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.read().decode("utf-8")
    except HTTPError as exc:
        try:
            body = json.loads(exc.read())
            message = body.get("message") or body.get("detail") or "请求失败"
        except (ValueError, UnicodeError):
            message = "请求失败"
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise RuntimeError(f"后端不可用: {exc.reason}") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description="拉取当前接口、依赖和版本历史")
    commands = parser.add_subparsers(dest="command", required=True)
    pull = commands.add_parser("pull-interfaces")
    pull.add_argument("--project", required=True)
    pull.add_argument("--api-base")
    pull.add_argument("--api-key", help="项目 token，也可设置 TEAMCODE_TOKEN")
    pull.add_argument("--format", choices=["json", "markdown"], default="markdown")
    pull.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        body = fetch(
            f"/api/projects/{quote(args.project, safe='')}/interfaces?format={args.format}",
            base=args.api_base,
            token=args.api_key,
        )
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(body, encoding="utf-8")
            print(f"已写入 {output}", file=sys.stderr)
        else:
            print(body)
        return 0
    except (RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
