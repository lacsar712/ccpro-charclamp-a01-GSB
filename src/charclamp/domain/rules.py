"""炭窑焖烧志业务规则。"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from charclamp.domain.models import BurnShift, Clamp, OxygenReading

MIN_PEAK_TEMP_FOR_DRAWN = 400.0
MAX_OXYGEN_PERCENT = 21.0
MAX_OXYGEN_FOR_DRAWN = 8.0
MIN_OXYGEN_READINGS_FOR_DRAWN = 4


class RuleError(ValueError):
    """业务规则校验失败。"""


def _to_utc(dt: datetime) -> datetime:
    """统一为带时区的 UTC，避免朴素时间与带时区时间混比。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def latest_shift_for_clamp(clamp: Clamp) -> BurnShift | None:
    if not clamp.shifts:
        return None
    return max(clamp.shifts, key=lambda s: _to_utc(s.started_at))


def sorted_oxygen_readings(clamp: Clamp) -> list[OxygenReading]:
    return sorted(clamp.oxygen_readings, key=lambda r: r.seq)


def validate_oxygen_reading(clamp: Clamp, seq: int, oxygen_percent: float) -> None:
    """
    登记一条测氧记录前的校验：
    仅焖烧中的炭窑可建簿；测次从 1 起且同窑不重复；氧百分为正且不超过 21。
    """
    if clamp.status != Clamp.STATUS_BURNING:
        raise RuleError("只有焖烧中的炭窑才能登记测氧，已码窑与已出炭禁止建簿")
    if seq is None or seq < 1:
        raise RuleError("测次必须从 1 起（正整数）")
    if (
        oxygen_percent is None
        or not math.isfinite(oxygen_percent)
        or oxygen_percent <= 0
        or oxygen_percent > MAX_OXYGEN_PERCENT
    ):
        raise RuleError(f"烟囱氧百分必须为正且不超过 {MAX_OXYGEN_PERCENT:.0f}")
    if any(r.seq == seq for r in clamp.oxygen_readings):
        raise RuleError(f"窑 {clamp.code} 第 {seq} 次测氧已登记，同窑测次不得重复")


def oxygen_log_ready_for_drawn(clamp: Clamp) -> tuple[bool, str]:
    """
    测氧簿一侧的出炭门槛：
    测次从 1 起连续且不少于 4 条；最新氧百分 <= 8%；
    最新采集时刻晚于该窑最近一班开始时刻。
    """
    readings = sorted_oxygen_readings(clamp)
    if not readings:
        return False, "该窑测氧簿为空，不能标记为已出炭"
    if len(readings) < MIN_OXYGEN_READINGS_FOR_DRAWN:
        return (
            False,
            f"测氧簿仅 {len(readings)} 条，少于 {MIN_OXYGEN_READINGS_FOR_DRAWN} 条，不能标记为已出炭",
        )
    seqs = [r.seq for r in readings]
    if seqs != list(range(1, len(seqs) + 1)):
        return False, "测次须从 1 起连续编号，当前簿页不连续，不能标记为已出炭"
    latest_reading = readings[-1]
    if not math.isfinite(latest_reading.oxygen_percent) or latest_reading.oxygen_percent > MAX_OXYGEN_FOR_DRAWN:
        return (
            False,
            f"最新烟囱氧百分 {latest_reading.oxygen_percent}% 高于 {MAX_OXYGEN_FOR_DRAWN:.0f}%，不能标记为已出炭",
        )
    latest_shift = latest_shift_for_clamp(clamp)
    if latest_shift is not None and _to_utc(latest_reading.sampled_at) <= _to_utc(latest_shift.started_at):
        return False, "最新测氧采集时刻未晚于该窑最近一班开始时刻，不能标记为已出炭"
    return True, ""


def can_mark_clamp_drawn(clamp: Clamp) -> tuple[bool, str]:
    """
    炭窑转为「已出炭」(drawn) 的前提——峰值与测氧并行门槛，缺一不可：
    1. 最近一条焖烧班次的峰值温度已记录，且 >= 400℃；
    2. 测氧簿满足 oxygen_log_ready_for_drawn 的全部条件。

    抽屉按钮与改窑态接口共用本函数，禁止另写放行逻辑。
    """
    latest = latest_shift_for_clamp(clamp)
    if latest is None:
        return False, "该窑尚无焖烧班次，不能标记为已出炭"
    if latest.peak_temp_c is None or not math.isfinite(latest.peak_temp_c):
        return False, "最近班次尚未记录峰值温度，不能标记为已出炭"
    if latest.peak_temp_c < MIN_PEAK_TEMP_FOR_DRAWN:
        return (
            False,
            f"最近班次峰值温度 {latest.peak_temp_c}℃ 低于 {MIN_PEAK_TEMP_FOR_DRAWN:.0f}℃，不能标记为已出炭",
        )
    return oxygen_log_ready_for_drawn(clamp)


def assert_can_set_clamp_status(clamp: Clamp, new_status: str) -> None:
    allowed = {Clamp.STATUS_STACKED, Clamp.STATUS_BURNING, Clamp.STATUS_DRAWN}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == Clamp.STATUS_DRAWN:
        ok, msg = can_mark_clamp_drawn(clamp)
        if not ok:
            raise RuleError(msg)
