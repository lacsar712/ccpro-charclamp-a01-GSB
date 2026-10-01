"""炭窑焖烧志业务规则。"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from charclamp.domain.models import BurnShift, Clamp, OxygenReading

MIN_PEAK_TEMP_FOR_DRAWN = 400.0
MIN_OXYGEN_READINGS_FOR_DRAWN = 4
MAX_OXYGEN_PCT_FOR_DRAWN = 8.0
OXYGEN_PCT_MAX_INPUT = 21.0


class RuleError(ValueError):
    """业务规则校验失败。"""


def latest_shift_for_clamp(clamp: Clamp) -> BurnShift | None:
    if not clamp.shifts:
        return None
    return max(clamp.shifts, key=lambda s: s.started_at)


def sorted_readings(clamp: Clamp) -> list[OxygenReading]:
    return sorted(clamp.oxygen_readings, key=lambda r: r.seq)


def _as_aware(value: datetime) -> datetime:
    """表单提交可能给出朴素时间，统一按 UTC 处理后再比较。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def validate_oxygen_reading(
    clamp: Clamp,
    seq: Any,
    oxygen_pct: Any,
    collected_at: Any,
    operator: str,
) -> None:
    """
    新建烟囱测氧记录前的全部业务校验：
    只有焖烧中能写；测次为从 1 起的正整数且同窑不重复；
    氧百分必须为正且不超过 21；采集时刻、当班人必填。

    注意：同窑测次重复还需数据库唯一约束兜底（并发提交）。
    """
    if clamp.status != Clamp.STATUS_BURNING:
        raise RuleError("只有焖烧中的炭窑才能登记烟囱测氧，已码窑与已出炭禁止建簿")

    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise RuleError("测次必须是从 1 起的正整数")

    if any(r.seq == seq for r in clamp.oxygen_readings):
        raise RuleError(f"第 {seq} 测已在簿：同窑测次不得重复，请改填下一测次")

    if (
        not isinstance(oxygen_pct, (int, float))
        or isinstance(oxygen_pct, bool)
        or not math.isfinite(oxygen_pct)
        or not (0 < oxygen_pct <= OXYGEN_PCT_MAX_INPUT)
    ):
        raise RuleError(f"烟囱氧百分必须为正且不超过 {OXYGEN_PCT_MAX_INPUT:.0f}")

    if not isinstance(collected_at, datetime):
        raise RuleError("请填写采集时刻")

    if not str(operator or "").strip():
        raise RuleError("请填写当班人")


def _oxygen_gate_reasons(clamp: Clamp, latest_shift: BurnShift) -> list[str]:
    """测氧簿门槛（与峰值门槛并行）。"""
    reasons: list[str] = []
    readings = sorted_readings(clamp)
    count = len(readings)
    if count < MIN_OXYGEN_READINGS_FOR_DRAWN:
        reasons.append(
            f"测氧簿不足 {MIN_OXYGEN_READINGS_FOR_DRAWN} 条（当前 {count} 条），不能标记为已出炭"
        )
    if readings:
        seqs = [r.seq for r in readings]
        expected = list(range(1, count + 1))
        if seqs != expected:
            reasons.append(f"测次不连续（应为 1～{count}），不能标记为已出炭")
        latest_reading = readings[-1]
        if latest_reading.oxygen_pct > MAX_OXYGEN_PCT_FOR_DRAWN:
            reasons.append(
                f"最新测氧 {latest_reading.oxygen_pct:g}% 高于 {MAX_OXYGEN_PCT_FOR_DRAWN:g}%，不能标记为已出炭"
            )
        if _as_aware(latest_reading.collected_at) <= _as_aware(latest_shift.started_at):
            reasons.append("最新测氧采集时刻不晚于最近一班开始时刻，不能标记为已出炭")
    return reasons


def can_mark_clamp_drawn(clamp: Clamp) -> tuple[bool, str]:
    """
    炭窑转为「已出炭」(drawn) 的统一放行函数——
    抽屉按钮与改窑态接口都读这里，禁止任何一侧另写放行。

    两套门槛并行，任一不过即拒绝：
    1. 峰值门槛：最近一条焖烧班次峰值已记录且 ≥ 400℃；
    2. 测氧门槛：测次自 1 起连续且不少于 4 条，
       最新氧百分 ≤ 8%，且最新采集晚于该窑最近一班开始时刻。
    """
    reasons: list[str] = []

    latest = latest_shift_for_clamp(clamp)
    if latest is None:
        return False, "该窑尚无焖烧班次，不能标记为已出炭"
    if latest.peak_temp_c is None:
        reasons.append("最近班次尚未记录峰值温度，不能标记为已出炭")
    elif latest.peak_temp_c < MIN_PEAK_TEMP_FOR_DRAWN:
        reasons.append(
            f"最近班次峰值温度 {latest.peak_temp_c}℃ 低于 {MIN_PEAK_TEMP_FOR_DRAWN:.0f}℃，不能标记为已出炭"
        )

    reasons.extend(_oxygen_gate_reasons(clamp, latest))

    if reasons:
        return False, "；".join(reasons)
    return True, ""


def assert_can_set_clamp_status(clamp: Clamp, new_status: str) -> None:
    allowed = {Clamp.STATUS_STACKED, Clamp.STATUS_BURNING, Clamp.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == Clamp.STATUS_DRAWN:
        ok, msg = can_mark_clamp_drawn(clamp)
        if not ok:
            raise RuleError(msg)
