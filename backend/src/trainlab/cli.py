import argparse
import getpass
import os
import sys

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trainlab.core.config import get_settings
from trainlab.core.security import hash_password, normalize_username
from trainlab.db.database import create_database_engine
from trainlab.db.models.user import User


def _create_user(
    username: str,
    display_name: str | None,
    password: str,
    *,
    owner: bool,
) -> int:
    if len(username.strip()) <= 6:
        print("账号必须大于 6 位", file=sys.stderr)
        return 2
    if len(password) <= 6:
        print("密码必须大于 6 位", file=sys.stderr)
        return 2

    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    try:
        with Session(engine) as db:
            normalized = normalize_username(username)
            existing_user = db.scalar(select(User).where(User.username_normalized == normalized))
            if existing_user is not None:
                if existing_user.is_owner == owner:
                    role = "主人账号" if owner else "用户"
                    print(f"{role} {existing_user.username} 已存在，无需重复创建")
                    return 0
                print("该用户名已存在", file=sys.stderr)
                return 3
            if owner and db.scalar(select(User).where(User.is_owner.is_(True))) is not None:
                print("系统已有主人账号，拒绝创建第二个主人", file=sys.stderr)
                return 3
            user = User(
                username=username.strip(),
                username_normalized=normalized,
                display_name=(display_name or username).strip(),
                password_hash=hash_password(password),
                is_owner=owner,
                is_active=True,
            )
            db.add(user)
            db.commit()
            role = "主人账号" if owner else "用户"
            print(f"已创建{role} {user.username}")
            return 0
    except SQLAlchemyError as exc:
        print("创建账号失败：请确认数据库已启动并完成迁移", file=sys.stderr)
        if settings.environment != "production":
            print(type(exc).__name__, file=sys.stderr)
        return 4
    finally:
        engine.dispose()


def create_owner(username: str, display_name: str | None, password: str) -> int:
    return _create_user(username, display_name, password, owner=True)


def create_user(username: str, display_name: str | None, password: str) -> int:
    return _create_user(username, display_name, password, owner=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trainlab")
    subparsers = parser.add_subparsers(dest="command", required=True)
    owner = subparsers.add_parser("create-owner", help="创建唯一的主人账号")
    owner.add_argument("--username", required=True)
    owner.add_argument("--display-name")
    owner.add_argument(
        "--password-env",
        help="从指定环境变量读取密码（自动化场景）",
    )
    user = subparsers.add_parser("create-user", help="创建普通登录用户")
    user.add_argument("--username", required=True)
    user.add_argument("--display-name")
    user.add_argument(
        "--password-env",
        help="从指定环境变量读取密码（自动化场景）",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command not in {"create-owner", "create-user"}:
        raise SystemExit(2)
    if args.password_env:
        password = os.environ.get(args.password_env)
        if password is None:
            print(f"环境变量 {args.password_env} 不存在", file=sys.stderr)
            raise SystemExit(2)
    else:
        password = getpass.getpass("密码：")
        confirmation = getpass.getpass("确认密码：")
        if password != confirmation:
            print("两次密码不一致", file=sys.stderr)
            raise SystemExit(2)
    create = create_owner if args.command == "create-owner" else create_user
    raise SystemExit(create(args.username, args.display_name, password))


if __name__ == "__main__":
    main()
