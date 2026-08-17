#!/usr/bin/env python3
"""Create a bounded, test-only prompt for a real coach-model invocation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any


def _module() -> Any:
    path = Path(__file__).resolve().parent / "build_context.py"
    spec = importlib.util.spec_from_file_location("trainlab_build_context", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("context_builder_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _instructions(mode: str) -> str:
    if mode == "daily":
        return """
你是 TrainLab 的 AI 教练。只使用下面 Host 提供的 JSON 证据，不读取任何 raw 文件、数据库、凭据、GPS 或其他目录，不调用任何外部服务。
请输出严格 JSON，schema_version 必须为 daily_ai_result_v1。日报必须区分 review_date 的昨日活动/非睡眠健康与 report_date 的已结束主睡眠。所有实测数值只能来自 bounded_metrics 中引用的证据；每个判断至少引用 evidence_refs 中一个 raw_file_id 和完全匹配的 sha256。bounded_metrics[].evidence_ref 必须直接填写对应 evidence_refs 项的 raw_file_id，不得填写数组位置。evidence_refs 只能引用 Host JSON 中实际存在且大于 0 的 raw_file_id；recent_trend_sha256 是结构化趋势输出的哈希，不是 raw_file_id，绝不能把它放进 evidence_refs，也不要把没有 raw 证据的趋势值放进 bounded_metrics。若历史趋势天数为 0，只说明历史趋势不可用，不要编造或把 0 当作一个 raw 指标。若 status=blocked，只返回稳定 error_code，不编造报告。
    若 safety 证据要求 caution，不得输出 ready。无论 safety 等级如何，都必须输出至少一条顶层 stop_conditions 数组，明确疼痛、胸痛、晕眩、异常呼吸或明显恢复不足时停止/降级；不要把 stop_conditions 塞进 summary 字符串。不要生成比赛配速锚。不要把任何凭据、GPS、原始内容、完整历史正文放进输出。provider_calls 必须为 0。
    """.strip()

    return """
你是 TrainLab 的 AI 教练。只使用下面 Host 提供的七份日报、最多四份历史周总结和 goal 摘要，不读取 raw 文件、数据库、凭据、GPS 或其他目录，不调用任何外部服务。
请输出严格 JSON，schema_version 必须为 weekly_ai_result_v1。period 必须逐字等于 Host context 的 period（这是本次复盘周，不是下周课表的日期范围）；training_plan 的七个 item 日期可以是复盘周之后的下一周。必须保留精确七份 daily_input_sha256，输出 evidence_refs 只引用日报 output_id/sha256。training_plan 必须覆盖连续七天、每天最多一个主课；running 必须给出正的 distance_km 或 duration_minutes，且 garmin_mapping_status 必须为 candidate；climbing 必须给出正的 duration_minutes 且 garmin_mapping_status 必须为 unsupported_skip；rest 不填写 distance_km、duration_minutes、pace、heart_rate 等剂量字段，garmin_mapping_status 必须为 unsupported_skip，并保留一个描述恢复结束条件的非剂量 steps 项（steps 不得为空）。所有 running 课程 name 必须以 -GTS 结尾，供未来发送器识别，攀岩和休息不添加该后缀。遵守 Easy/SOS、跑攀统一硬负荷最多三次且任意两次相隔两个完整日历日、不补课、不同时增加距离和强度、红旗优先降级或休息。无比赛目标时不得出现比赛配速锚。不要编造缺失数据；provider_calls 必须为 0。
""".strip()


def _atomic_owner_only_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def create(
    mode: str,
    target: date,
    database: Path,
    source_root: Path,
    context_path: Path,
    prompt_path: Path,
) -> dict[str, Any]:
    module = _module()
    context = (
        module.build_daily_context(database, source_root, target)
        if mode == "daily"
        else module.build_weekly_context(database, source_root, target)
    )
    _atomic_owner_only_write(
        context_path,
        json.dumps(context, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )
    prompt = (
        _instructions(mode)
        + "\n\nHost evidence JSON (the only allowed input):\n"
        + json.dumps(context, ensure_ascii=False, sort_keys=True)
        + "\n\nReturn JSON only."
    )
    _atomic_owner_only_write(prompt_path, prompt + "\n")
    return context


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("daily", "weekly"), required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--context-json", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    args = parser.parse_args()
    create(
        args.mode,
        date.fromisoformat(args.date),
        args.database,
        args.source_root,
        args.context_json,
        args.prompt,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
