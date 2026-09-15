"""Local prepare APIs; every weekly consumer reads the same R4 seal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skills._shared.fit_weekly import (
    fit_sync,
    garmin_workouts,
    gmail_message,
    report_artifacts,
    storage,
    sync_batch,
    sync_calendar,
)
from skills._shared.fit_weekly import publication_ledger as ledger


def weekly_request(
    bundle: report_artifacts.Bundle,
    end: str,
    action: str,
    kind: str,
    date: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "fit_delivery_request_v1",
        "action_key": action,
        "kind": kind,
        "source_key": "weekly:" + end,
        "source_sha256": ledger.sha(bundle.manifest),
        "date": date,
        "payload": payload,
    }


def prepare_weekly(
    root: Path,
    end: str,
    revision_id: str,
    revision_sha: str,
    *,
    recipient: str,
    sender: str,
    late: bool,
    mail_version: int = 2,
) -> dict[str, Any]:
    if type(late) is not bool:
        raise ValueError("publication_late_flag_invalid")
    gmail_message.address(recipient)
    gmail_message.address(sender)
    seal = report_artifacts.seal(root, end, revision_id, revision_sha)
    bundle = report_artifacts.read_sealed(root, end)
    slot = sync_calendar.weekly_slot(end)
    date = (
        sync_calendar.utc_time(end)
        .astimezone(sync_calendar.HONG_KONG)
        .date()
        .isoformat()
    )
    mail_key = f"weekly:{end}:gmail"
    label = "（补发）" if late else ""
    subject = (
        weekly_subject(end) if mail_version == 2 else f"TrainLab 周报 {date}{label}"
    )
    body = f"训练周报{label}\n原统计周期：{slot['start_utc']} 至 {end}（起点包含，终点不包含）。\n固定跑步计划：{slot['plan_dates'][0]} 至 {slot['plan_dates'][-1]}。\n完整总结、课程与数据局限见附件。运动表现不能证明没有健康风险。"
    payload = gmail_message.build(
        mail_key, sender, recipient, subject, body, bundle.pdf
    )
    payload["late"] = late
    with storage.open_store(root) as db:
        previous = ledger.document(db, ledger.key(mail_key, "request"))
    request = weekly_request(bundle, end, mail_key, "gmail", date, payload)
    if mail_version == 2:
        request["schema_version"] = "fit_delivery_request_v2"
    if previous is not None:
        for field in ("source_key", "source_sha256", "date"):
            if previous[field] != request[field]:
                raise ValueError("publication_source_conflict")
        if any(
            previous["payload"][k] != payload[k]
            for k in ("sender", "recipient", "late", "pdf_sha256")
        ):
            raise ValueError("publication_selection_conflict")
        request = previous
    requests = [request]
    courses = []
    for day in bundle.plan["days"]:
        if day["kind"] == "rest":
            continue
        create = f"weekly:{end}:create:{day['date']}"
        schedule = f"weekly:{end}:schedule:{day['date']}"
        requests.append(
            weekly_request(
                bundle,
                end,
                create,
                "garmin_create",
                day["date"],
                {"workout_data": garmin_workouts.convert(day)},
            )
        )
        requests.append(
            weekly_request(
                bundle,
                end,
                schedule,
                "garmin_schedule",
                day["date"],
                {"create_action": create, "calendar_date": day["date"]},
            )
        )
        courses.append({"create": create, "schedule": schedule})
    for req in requests:
        ledger.prepare(root, req)
    if requests[0]["schema_version"] == "fit_delivery_request_v2":
        from skills._shared.fit_weekly import gmail_labels

        gmail_labels.prepare(root, requests[0])
    return {"seal": seal, "mail": mail_key, "workouts": courses}


def sync_snapshot(root: Path, job_key: str) -> dict[str, Any]:
    collection_key = "fit-sync:" + storage.digest(job_key.encode())
    with storage.open_store(root) as db:
        row = db.execute(
            "SELECT input_json,input_sha256 FROM sync_jobs WHERE job_key=?", (job_key,)
        ).fetchone()
        collection_request = fit_sync.document(db, f"{collection_key}:request")
        if row is None and collection_request is None:
            raise ValueError("publication_sync_source_missing")
        if row is not None:
            if storage.digest(row[0].encode()) != row[1]:
                raise ValueError("publication_sync_source_invalid")
            inputs = json.loads(row[0])
            sync_calendar.InventoryRequest(**inputs).validate()
        else:
            spec = fit_sync.read_request(collection_request)
            inputs = {
                "start_date": spec.inventory.start_date,
                "end_date": spec.inventory.end_date,
            }
        done = fit_sync.document(db, f"{collection_key}:complete")
        inventory = fit_sync.document(db, f"inventory:{job_key}")
        day_rows = {
            r[0]: {"date": r[0], "status": r[1], "activity_count": r[2]}
            for r in db.execute(
                "SELECT day,status,activity_count FROM sync_days WHERE job_key=? ORDER BY day",
                (job_key,),
            )
        }
        days = []
        for day in sync_calendar.days_between(
            sync_calendar.day_value(inputs["start_date"]),
            sync_calendar.day_value(inputs["end_date"]),
        ):
            days.append(
                day_rows.get(
                    day,
                    {
                        "date": day,
                        "status": "gap"
                        if sync_calendar.day_status(db, day) == "gap"
                        else "incomplete",
                        "activity_count": None,
                    },
                )
            )
        errors = db.execute(
            "SELECT COUNT(*) FROM sync_results WHERE job_key=? AND status='error'",
            (job_key,),
        ).fetchone()[0]
        collection_errors = [
            r
            for r in db.execute(
                "SELECT content_json FROM documents WHERE kind='sync_receipt' AND substr(logical_key,1,?)=?",
                (len(f"{collection_key}:"), f"{collection_key}:"),
            )
            if json.loads(r[0]).get("status") in ("error", "failed")
        ]
        return {
            "job_key": job_key,
            "start_date": inputs["start_date"],
            "end_date": inputs["end_date"],
            "days": days,
            "inventory_complete": bool(
                inventory and inventory.get("inventory_complete")
            ),
            "collection_complete": done is not None
            or bool(inventory and inventory.get("collection_complete")),
            "activity_count": done["activity_count"]
            if done
            else inventory.get("activity_count")
            if inventory
            else None,
            "fit_count": done["fit_count"] if done else None,
            "no_fit_count": done["no_fit_count"] if done else None,
            "error_count": errors + len(collection_errors),
        }


def prepare_sync(
    root: Path, job_key: str, *, recipient: str, sender: str, mail_version: int = 2
) -> str:
    snapshot = sync_snapshot(root, job_key)
    action = f"sync:{job_key}:gmail"
    labels = {
        "complete": "查询完整",
        "provisional": "当日暂定",
        "gap": "缺口",
        "incomplete": "查询不完整",
    }
    lines = [f"同步任务：{job_key}"]
    for day in snapshot["days"]:
        count = day["activity_count"]
        detail = (
            "；完整查询确认无运动"
            if day["status"] == "complete" and count == 0
            else f"；活动数：{count if count is not None else '未知'}"
        )
        lines.append(f"{day['date']}：{labels[day['status']]}{detail}")

    def known(value: Any) -> Any:
        return value if value is not None else "未知"

    lines.append(
        f"FIT收集：{'完成' if snapshot['collection_complete'] else '未完成'}；已取得FIT：{known(snapshot['fit_count'])}；无FIT：{known(snapshot['no_fit_count'])}；错误：{snapshot['error_count']}。"
    )
    payload = gmail_message.build(
        action,
        sender,
        recipient,
        f"TrainLab 同步 {snapshot['end_date']}",
        "\n".join(lines),
    )
    payload["sync_snapshot"] = snapshot
    return ledger.prepare(
        root,
        {
            "schema_version": f"fit_delivery_request_v{mail_version}",
            "action_key": action,
            "kind": "gmail",
            "source_key": f"sync:{job_key}",
            "source_sha256": ledger.sha(snapshot),
            "date": snapshot["end_date"],
            "payload": payload,
        },
    )


def validate_source(root: Path, action: str) -> dict[str, Any]:
    with storage.open_store(root) as db:
        req = ledger.request(db, action)
    if req["kind"] in ("gmail_label_ensure", "gmail_label_apply"):
        from skills._shared.fit_weekly import gmail_labels

        return gmail_labels.validate(root, req)
    if req["source_key"].startswith("weekly:"):
        end = req["source_key"].removeprefix("weekly:")
        bundle = report_artifacts.read_sealed(root, end)
        if ledger.sha(bundle.manifest) != req["source_sha256"]:
            raise ValueError("publication_seal_conflict")
        if req["kind"] == "gmail":
            if req["payload"]["pdf_sha256"] != storage.digest(bundle.pdf):
                raise ValueError("publication_pdf_conflict")
        else:
            day = next(d for d in bundle.plan["days"] if d["date"] == req["date"])
            if day["kind"] != "run" or (
                req["kind"] == "garmin_create"
                and req["payload"] != {"workout_data": garmin_workouts.convert(day)}
            ):
                raise ValueError("publication_plan_conflict")
    elif req["source_key"].startswith("sync-batch:"):
        saved = sync_batch.read(root, req["source_key"])
        if (
            saved is None
            or saved != req["payload"].get("sync_batch")
            or ledger.sha(saved) != req["source_sha256"]
        ):
            raise ValueError("publication_sync_batch_binding_invalid")
    elif req["source_key"].startswith("sync:"):
        saved = req["payload"]["sync_snapshot"]
        if ledger.sha(saved) != req["source_sha256"]:
            raise ValueError("publication_sync_binding_invalid")
        # Completed/current sources cannot silently change this prepared mail.
        if sync_snapshot(root, req["source_key"].removeprefix("sync:")) != saved:
            raise ValueError("publication_sync_source_changed")
    else:
        raise ValueError("publication_source_invalid")
    if req["kind"] == "gmail":
        gmail_message.verify(
            gmail_message.decode(req["payload"]["raw"]), req["payload"]
        )
    return req


def prepare_sync_batch(
    root: Path, batch_key: str, *, recipient: str, sender: str, mail_version: int = 2
) -> str:
    saved = sync_batch.read(root, batch_key)
    if saved is None:
        raise ValueError("publication_sync_batch_unsealed")
    action = batch_key + ":gmail"
    lines = [f"同步批次：{batch_key}", "实际查询日期：" + "、".join(saved["dates"])]
    labels = {
        "complete": "查询完整",
        "provisional": "当日暂定",
        "gap": "缺口",
        "incomplete": "查询不完整",
    }
    for segment in saved["segments"]:
        lines.append(f"子任务：{segment['job_key']}；结果：{segment['status']}")
        snapshot = segment["snapshot"]
        if snapshot is None:
            lines.append("查询未启动；活动及 FIT 数量未知。")
        else:
            for day in snapshot["days"]:
                count = day["activity_count"]
                detail = (
                    "完整查询确认无运动"
                    if day["status"] == "complete" and count == 0
                    else f"活动数：{count if count is not None else '未知'}"
                )
                lines.append(f"{day['date']}：{labels[day['status']]}；{detail}")
            lines.append(
                f"FIT收集：{'完成' if snapshot['collection_complete'] else '未完成'}；FIT：{snapshot['fit_count']}；无FIT：{snapshot['no_fit_count']}；错误：{snapshot['error_count']}"
            )
        for call in segment["calls"]:
            result = call["outcome"]
            state = result["status"] if result else "unknown"
            lines.append(f"调用 {call['ordinal']}（{call['kind']}）：{state}")
    payload = gmail_message.build(
        action,
        sender,
        recipient,
        f"TrainLab 同步 {saved['dates'][-1]}",
        "\n".join(lines),
    )
    payload["sync_batch"] = saved
    return ledger.prepare(
        root,
        {
            "schema_version": f"fit_delivery_request_v{mail_version}",
            "action_key": action,
            "kind": "gmail",
            "source_key": batch_key,
            "source_sha256": ledger.sha(saved),
            "date": saved["dates"][-1],
            "payload": payload,
        },
    )


def weekly_subject(end: str) -> str:
    slot = sync_calendar.weekly_slot(end)
    if slot["end_utc"] != end:
        raise ValueError("publication_period_invalid")

    def chinese(value: str) -> str:
        day = sync_calendar.day_value(value)
        return f"{day.year}年{day.month}月{day.day}日"

    start = (
        sync_calendar.utc_time(slot["start_utc"])
        .astimezone(sync_calendar.HONG_KONG)
        .date()
        .isoformat()
    )
    finish = (
        sync_calendar.utc_time(end)
        .astimezone(sync_calendar.HONG_KONG)
        .date()
        .isoformat()
    )
    return f"TrainLab｜每周训练报告｜回顾{chinese(start)}—{chinese(finish)}｜计划{chinese(slot['plan_dates'][0])}—{chinese(slot['plan_dates'][-1])}"
