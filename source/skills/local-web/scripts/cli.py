from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from trainlab.contracts.web import static_mount_dir
from trainlab.local_web.server import WebAppSettings, create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="启动本机 Web 登录与认证维护；Ctrl-C 停服。")
    parser.add_argument("--instance-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    if not (args.project_root / static_mount_dir() / "index.html").is_file():
        parser.exit(2, "前端未构建。请在 source/frontend 执行 npm ci && npm run build 后重试。\n")
    app = create_app(WebAppSettings(instance_root=args.instance_root, project_root=args.project_root))
    print("打开 http://127.0.0.1:8080 选择区域并登录；Ctrl-C 停服。", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8080, workers=1, reload=False,
                proxy_headers=False, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
