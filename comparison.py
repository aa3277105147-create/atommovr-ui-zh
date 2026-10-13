"""Compare original atommovr algorithms from one frozen initial array."""

from __future__ import annotations

import copy
import math
import time
from typing import Any

import simulator


TABLE_HEADERS = [
    "算法", "状态", "目标填充", "光镊上限", "最大同时使用", "移动批次", "成功搬运次数",
    "成功搬运距离（µm）", "模拟物理时间（µs）",
]

_LABELS = {
    "parallel": "并行 Hungarian",
    "hungarian": "Hungarian（顺序搬运）",
    "bcv2": "Balance & Compact（BCv2）",
    "bc": "Balance & Compact（BC）",
    "lbap": "并行 LBAP",
    "parallel_lbap": "并行 LBAP",
    "generalized": "Generalized Balance（广义平衡）",
}
_STATUS_TEXT = {
    "success": "目标已填满", "incomplete": "未完全填满",
    "insufficient": "原子不足", "algorithm_error": "执行失败",
    "invalid": "参数无效", "skipped": "不支持此图案", "blocked": "避碰安全停止", "not_run": "尚未执行",
}


def _algorithm_label(key: str, implementation: Any) -> str:
    labels = getattr(simulator, "ALGORITHM_NAMES", getattr(simulator, "ALGORITHM_LABELS", {}))
    return labels.get(key, _LABELS.get(key, getattr(implementation, "__name__", key)))


def _supports_pattern(key: str, pattern: str) -> bool:
    supported = getattr(simulator, "SUPPORTED_PATTERNS_BY_ALGORITHM", getattr(simulator, "ALGORITHM_PATTERNS", {}))
    if key in supported:
        return pattern in supported[key]
    return pattern == "center" if key in ("bc", "bcv2") else True


def _successful_transports(result: dict[str, Any], spacing_um: float) -> tuple[int, float]:
    """Count successful nonzero-distance commands originating at occupied sites.

    AOD completion may record empty-site commands and failed pickups. They are
    deliberately excluded, as are transport/putdown losses whose actual
    traveled distances are not available in the library's event records.
    """
    count = 0
    distance = 0.0
    for frame in result.get("frames", []):
        before = frame.get("before", [])
        for move in frame.get("moves", []):
            if move.get("event") != 0 or move.get("flag") != 0:
                continue
            source, destination = move.get("from"), move.get("to")
            if not isinstance(source, (tuple, list)) or not isinstance(destination, (tuple, list)):
                continue
            if len(source) != 2 or len(destination) != 2:
                continue
            r, c = source
            if not (isinstance(r, int) and isinstance(c, int) and
                    0 <= r < len(before) and 0 <= c < len(before[r]) and before[r][c]):
                continue
            length = math.hypot(destination[0] - r, destination[1] - c)
            if length <= 0:
                continue
            count += 1
            distance += length * spacing_um
    return count, distance


def _footnote(noise: bool) -> str:
    text = (
        "各算法使用相同的初始分布、目标和物理参数，保留目标外原子。结果包含本平台的数量限制与避碰调度。"
        "支持多光镊的算法使用所选数量上限，保守串行选项固定为 1；光镊数量包括 AOD 空位交点。"
        "成功搬运次数是原子成功移动的次数，同一原子多次移动会重复计数。"
        "搬运距离仅累计这些成功动作的路径长度。模拟物理时间按批次及相邻动作的衔接规则累计，与动画播放速度无关。"
    )
    if noise:
        text += (
            "误差模式只比较一次试验，固定同一误差种子；"
            "各算法执行顺序与随机数消耗不同，单个种子的结果不是统计成功率；"
            "距离更短也可能来自搬运失败，需要结合目标填充率判断。"
        )
    return text


def _row(key: str, label: str, summary: dict[str, Any], successful_moves: int | None,
         successful_distance_um: float | None, target_count: int,
         tweezer_count: int | None = None) -> dict[str, Any]:
    status = summary.get("status", "algorithm_error")
    filled = summary.get("filled")
    total = summary.get("target_count", target_count)
    fill_fraction = filled / total if filled is not None and total else None
    fill_text = "—" if filled is None else f"{filled}/{total}"
    if fill_fraction is not None:
        fill_text += f" ({fill_fraction * 100:.1f}%)"
    elapsed = summary.get("simulated_time")
    return {
        "algorithm": label, "key": key, "status": status,
        "status_text": _STATUS_TEXT.get(status, status), "filled": filled,
        "target_count": total, "fill_fraction": fill_fraction, "fill_text": fill_text,
        "tweezer_count": summary.get("tweezer_count", tweezer_count),
        "max_active_tweezers": summary.get("max_active_tweezers"),
        "executed_batches": summary.get("executed_batches"),
        "successful_moves": successful_moves,
        "successful_distance_um": successful_distance_um,
        "simulated_time_us": None if elapsed is None else elapsed * 1_000_000,
        "message": summary.get("message", ""),
        "losses": summary.get("losses"),
    }


def _table_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    def number(value: int | float | None) -> int | float | str:
        return "—" if value is None else round(value, 6)
    return [[
        row["algorithm"], row["status_text"], row["fill_text"],
        number(row["tweezer_count"]), number(row["max_active_tweezers"]),
        number(row["executed_batches"]), number(row["successful_moves"]),
        number(row["successful_distance_um"]), number(row["simulated_time_us"]),
    ] for row in rows]


def compare_algorithms(config: dict[str, Any] | None = None, *, deadline=None, on_progress=None) -> dict[str, Any]:
    """Run every available native algorithm with one identical frozen matrix.

    The returned config remains the normalized *original* user configuration.
    Per-algorithm copies use manual initial arrays solely to freeze the same
    random/manual preview. simulate() preserves native error seeds and already
    applies process time/resource limits and do_ejection=False.
    """
    base = simulator.preview(copy.deepcopy(config))
    normalized = copy.deepcopy(base.get("config", {}))
    footnote = _footnote(bool(normalized.get("noise")))
    result = {
        "config": normalized, "initial_matrix": copy.deepcopy(base.get("initial", [])),
        "rows": [], "table_headers": list(TABLE_HEADERS), "table_rows": [],
        "footnote": footnote, "status": "invalid", "message": "",
    }
    base_summary = base.get("summary", {})
    if base_summary.get("status") in ("invalid", "algorithm_error") or not result["initial_matrix"]:
        result["status"] = base_summary.get("status", "invalid")
        result["message"] = base_summary.get("message", "无法生成用于比较的初态。")
        return result

    frozen = copy.deepcopy(result["initial_matrix"])
    target_count = base_summary.get("target_count", 0)
    rows = []
    for key, implementation in list(simulator.ALGORITHMS.items()):
        label = _algorithm_label(key, implementation)
        if not _supports_pattern(key, normalized["pattern"]):
            rows.append(_row(key, label, {
                "status": "skipped", "target_count": target_count,
                "message": f"{label} 在本演示中不支持当前目标图案，已跳过。",
            }, None, None, target_count))
            continue
        if deadline is not None and time.monotonic() >= deadline:
            rows.append(_row(key, label, {"status": "not_run", "target_count": target_count,
                "message": "达到本轮统计的计算时限，尚未执行。"}, None, None, target_count))
            continue
        candidate = copy.deepcopy(normalized)
        candidate.update(algorithm=key, initial_mode="manual", initial_matrix=copy.deepcopy(frozen))
        if key not in simulator.MULTI_TWEEZER_ALGORITHMS:
            candidate["tweezer_count"] = 1
        try:
            simulation = simulator.simulate(candidate)
            moves, distance = _successful_transports(simulation, normalized["spacing_um"])
            summary = dict(simulation.get("summary", {}))
            if not simulation.get("initial") and not simulation.get("frames") and summary.get("status") in ("algorithm_error", "invalid"):
                # A worker may fail before it reports an initial state. The known
                # target is retained, but unobserved execution metrics are unknown.
                summary.update(target_count=target_count, filled=None, losses=None,
                               simulated_time=None, executed_batches=None, max_active_tweezers=None)
                moves = distance = None
            rows.append(_row(key, label, summary, moves, distance, target_count,
                             candidate.get("tweezer_count", 1)))
        except Exception as error:
            rows.append(_row(key, label, {
                "status": "algorithm_error", "target_count": target_count,
                "message": f"{label} 比较失败：{type(error).__name__}: {error}。",
            }, None, None, target_count, candidate.get("tweezer_count", 1)))
        if on_progress:
            on_progress(key)
    partial = any(row['status'] == 'not_run' for row in rows)
    result.update(rows=rows, table_rows=_table_rows(rows), status="partial" if partial else "complete",
                  message=f"已执行同一初态下的 {sum(row['status'] not in ('skipped', 'not_run') for row in rows)} 种算法。")
    return result
