import argparse
import getpass
import os
import sys
import uuid
from contextlib import suppress

from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from trainlab.core.config import get_settings
from trainlab.core.security import hash_password, normalize_username
from trainlab.db.database import create_database_engine
from trainlab.db.models.user import User
from trainlab.services.activity_reparse import ActivityReparseError, reparse_fit_imports
from trainlab.services.activity_storage import PrivateActivityStorage, StorageError
from trainlab.services.storage_usage import reconcile_storage
from trainlab.services.user_admin import (
    UsernameConflictError,
    UserNotFoundError,
    configure_development_owner,
    reset_password_and_revoke_sessions,
    revoke_all_sessions,
)


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


def reset_password(username: str, password: str) -> int:
    if len(username.strip()) <= 6:
        print("账号必须大于 6 位", file=sys.stderr)
        return 2
    if len(password) <= 6:
        print("密码必须大于 6 位", file=sys.stderr)
        return 2

    engine: Engine | None = None
    try:
        settings = get_settings()
        engine = create_database_engine(settings.database_url)
        with Session(engine) as db:
            reset_password_and_revoke_sessions(db, username, password)
        print("密码已重置，已有会话已撤销")
        return 0
    except UserNotFoundError:
        print("用户不存在", file=sys.stderr)
        return 3
    except Exception:
        print("密码重置失败：请确认数据库已启动并完成迁移", file=sys.stderr)
        return 4
    finally:
        if engine is not None:
            with suppress(Exception):
                engine.dispose()


def revoke_sessions(username: str) -> int:
    if len(username.strip()) <= 6:
        print("账号必须大于 6 位", file=sys.stderr)
        return 2

    engine: Engine | None = None
    try:
        settings = get_settings()
        engine = create_database_engine(settings.database_url)
        with Session(engine) as db:
            revoke_all_sessions(db, username)
        print("已有会话已撤销")
        return 0
    except UserNotFoundError:
        print("用户不存在", file=sys.stderr)
        return 3
    except Exception:
        print("会话撤销失败：请确认数据库已启动并完成迁移", file=sys.stderr)
        return 4
    finally:
        if engine is not None:
            with suppress(Exception):
                engine.dispose()


def set_development_owner(username: str, password: str) -> int:
    if len(username.strip()) <= 6:
        print("账号必须大于 6 位", file=sys.stderr)
        return 2
    if len(password) <= 6:
        print("密码必须大于 6 位", file=sys.stderr)
        return 2

    engine: Engine | None = None
    try:
        settings = get_settings()
        if settings.environment != "development":
            print("开发主人账号命令仅允许在 development 环境运行", file=sys.stderr)
            return 3
        engine = create_database_engine(settings.database_url)
        with Session(engine) as db:
            configure_development_owner(db, username, password)
        print("开发主人账号已配置，已有会话已撤销")
        return 0
    except UsernameConflictError:
        print("目标用户名已被其他用户占用", file=sys.stderr)
        return 3
    except Exception:
        print("开发主人账号配置失败：请确认数据库已启动并完成迁移", file=sys.stderr)
        return 4
    finally:
        if engine is not None:
            with suppress(Exception):
                engine.dispose()


def reconcile_private_storage(*, apply: bool) -> int:
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    try:
        with Session(engine) as db:
            report = reconcile_storage(
                db,
                PrivateActivityStorage(settings.private_storage_root),
                settings.storage_staging_grace_minutes,
                apply=apply,
            )
        mode = "apply" if apply else "dry-run"
        print(
            f"mode={mode} candidates={report.candidate_count} "
            f"candidate_bytes={report.candidate_bytes} removed={report.removed_count} "
            f"removed_bytes={report.removed_bytes}"
        )
        return 0
    except (SQLAlchemyError, StorageError):
        print("存储审计失败：请确认数据库、迁移和私有存储可用", file=sys.stderr)
        return 4
    finally:
        engine.dispose()


def reparse_fit(username: str, import_ids: list[uuid.UUID], *, apply: bool) -> int:
    if len(username.strip()) <= 6:
        print("账号必须大于 6 位", file=sys.stderr)
        return 2
    engine: Engine | None = None
    try:
        settings = get_settings()
        engine = create_database_engine(settings.database_url)
        with Session(engine) as db:
            report = reparse_fit_imports(
                db,
                PrivateActivityStorage(settings.private_storage_root),
                username,
                import_ids,
                apply=apply,
            )
        mode = "apply" if report.applied else "dry-run"
        print(f"mode={mode} imports={len(report.items)}")
        for item in report.items:
            print(
                f"import_id={item.import_id} activity_id={item.activity_id} "
                f"status={item.status} records={item.record_count} "
                f"laps={item.lap_count} segments={item.segment_count}"
            )
        return 0
    except ActivityReparseError as exc:
        print(f"FIT 完整重解析未执行 code={exc.code}", file=sys.stderr)
        return 3 if exc.code in {"user_not_found", "import_not_found"} else 4
    except Exception:
        print("FIT 完整重解析失败：请确认数据库、迁移和私有存储可用", file=sys.stderr)
        return 4
    finally:
        if engine is not None:
            with suppress(Exception):
                engine.dispose()


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
    reset = subparsers.add_parser("reset-password", help="重置指定用户密码并撤销其全部会话")
    reset.add_argument("--username", required=True)
    reset.add_argument(
        "--password-env",
        help="从指定环境变量读取密码（自动化场景）",
    )
    revoke = subparsers.add_parser("revoke-sessions", help="撤销指定用户的全部会话")
    revoke.add_argument("--username", required=True)
    development_owner = subparsers.add_parser(
        "set-development-owner",
        help="创建或原子更新仅限本机开发环境的主人账号",
    )
    development_owner.add_argument("--username", required=True)
    development_owner.add_argument(
        "--password-env",
        help="从指定环境变量读取开发密码（自动化场景）",
    )
    reconcile = subparsers.add_parser("reconcile-storage", help="审计无数据库引用的私有存储文件")
    reconcile.add_argument(
        "--apply",
        action="store_true",
        help="删除超过宽限期的孤儿文件；省略时仅审计",
    )
    reparse = subparsers.add_parser("reparse-fit", help="预检或原子重建指定用户的 FIT 活动投影")
    reparse.add_argument("--username", required=True)
    reparse.add_argument(
        "--import-id",
        action="append",
        type=uuid.UUID,
        required=True,
        dest="import_ids",
    )
    reparse.add_argument(
        "--apply",
        action="store_true",
        help="原子替换投影；省略时仅预检",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "reconcile-storage":
        raise SystemExit(reconcile_private_storage(apply=args.apply))
    if args.command == "reparse-fit":
        raise SystemExit(reparse_fit(args.username, args.import_ids, apply=args.apply))
    if args.command == "revoke-sessions":
        raise SystemExit(revoke_sessions(args.username))
    if args.command not in {
        "create-owner",
        "create-user",
        "reset-password",
        "set-development-owner",
    }:
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
    if args.command == "reset-password":
        raise SystemExit(reset_password(args.username, password))
    if args.command == "set-development-owner":
        raise SystemExit(set_development_owner(args.username, password))
    create = create_owner if args.command == "create-owner" else create_user
    raise SystemExit(create(args.username, args.display_name, password))


if __name__ == "__main__":
    main()
