"""Data adapter for the original atommovr library and the local demo UI."""

from __future__ import annotations

import copy
import math
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable

# Developers may point the UI at a complete atommovr source checkout. Normal
# installations can leave this unset and import the installed package.
_source_override = os.environ.get("ATOMMOVR_SOURCE")
if _source_override:
    SOURCE_ROOT = Path(_source_override).expanduser().resolve()
    if not (SOURCE_ROOT / "atommovr").is_dir():
        raise RuntimeError(
            "ATOMMOVR_SOURCE 必须指向包含 atommovr 包的完整源码目录。"
        )
    if str(SOURCE_ROOT) not in sys.path:
        sys.path.insert(0, str(SOURCE_ROOT))

import numpy as np

from atommovr.algorithms.single_species import (
    BCv2,
    BalanceAndCompact,
    GeneralizedBalance,
    Hungarian,
    ParallelHungarian,
    ParallelLBAP,
)
from atommovr.utils.AtomArray import AtomArray
from atommovr.utils.core import Configurations, PhysicalParams, random_loading
from atommovr.utils.errormodels import UniformVacuumTweezerError, ZeroNoise
from atommovr.utils.failure_policy import FailureEvent
from scheduling import check_batch, schedule_moves, source


DEFAULT_CONFIG = {
    "n": 10,
    "target_size": 4,
    "loading_prob": 0.6,
    "seed": 42,
    "algorithm": "parallel",
    "pattern": "center",
    "speed": 0.1,
    "spacing_um": 5.0,
    "noise": False,
    "lifetime": 30.0,
    "pickup_success": 99.0,
    "putdown_success": 99.0,
    "initial_mode": "random",
    "initial_matrix": None,
    "tweezer_count": 4,
    "pickup_time_us": 0.0,
    "putdown_time_us": 0.0,
    "accel_time_us": 0.0,
    "decel_time_us": 0.0,
}

ALGORITHMS = {
    "parallel": ParallelHungarian,
    "hungarian": Hungarian,
    "lbap": ParallelLBAP,
    "generalized": GeneralizedBalance,
    "bcv2": BCv2,
    "bc": BalanceAndCompact,
}
ALGORITHM_NAMES = {
    "parallel": "并行 Hungarian",
    "hungarian": "Hungarian（顺序搬运）",
    "lbap": "并行 LBAP（瓶颈匹配）",
    "generalized": "Generalized Balance（广义平衡）",
    "bcv2": "BCv2（优化平衡压缩）",
    "bc": "BC（传统平衡压缩）",
}
PATTERNS = {
    "center": Configurations.MIDDLE_FILL,
    "checkerboard": Configurations.CHECKERBOARD,
    "horizontal": Configurations.ZEBRA_HORIZONTAL,
    "vertical": Configurations.ZEBRA_VERTICAL,
}
SUPPORTED_PATTERNS_BY_ALGORITHM = {
    name: ("center",) if name in ("bc", "bcv2") else tuple(PATTERNS)
    for name in ALGORITHMS
}
# Both names expose the same contract for selectors and comparison callers.
ALGORITHM_PATTERNS = SUPPORTED_PATTERNS_BY_ALGORITHM
MULTI_TWEEZER_ALGORITHMS = frozenset({"parallel", "generalized", "bcv2", "bc"})
MAX_TWEEZERS = 24
SIMULATION_TIMEOUT_SECONDS = 20.0
MAX_BATCHES = 2000
MAX_PLANNED_MOVES = 50_000


class RecordingErrorModel(UniformVacuumTweezerError):
    """Preserve library behavior while recording the sites lost to vacuum."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.vacuum_losses: list[list[int]] = []

    def get_atom_loss(self, state, evolution_time, n_species=1):
        after, flag = super().get_atom_loss(state, evolution_time, n_species)
        before_2d = state[:, :, 0] if state.ndim == 3 else state
        after_2d = after[:, :, 0] if after.ndim == 3 else after
        self.vacuum_losses = np.argwhere(
            (before_2d > 0) & (after_2d == 0)
        ).astype(int).tolist()
        return after, flag


class RecordingAtomArray(AtomArray):
    """Observe actual applied moves, including the library's AOD completion."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.applied_moves = []
        self.overlap_losses: list[list[int]] = []
        self.overlap_lost_atoms = 0

    def move_atoms(self, move_list, prev_move_list=None, next_move_list=None):
        self.applied_moves = []
        self.overlap_losses = []
        self.overlap_lost_atoms = 0
        if hasattr(self.error_model, "vacuum_losses"):
            self.error_model.vacuum_losses = []
        return super().move_atoms(move_list, prev_move_list, next_move_list)

    def _apply_moves(self, moves):
        outcome = super()._apply_moves(moves)
        self.applied_moves = moves
        return outcome

    def _eject_dual_occupied_sites_inplace(self, move_list, source_rows, source_cols):
        occupancy = self.matrix.sum(axis=-1, dtype=np.int64)
        overlap = occupancy > 1
        self.overlap_losses = np.argwhere(overlap).astype(int).tolist()
        self.overlap_lost_atoms = int(occupancy[overlap].sum())
        return super()._eject_dual_occupied_sites_inplace(
            move_list, source_rows, source_cols
        )


def _empty_result(config: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "config": copy.deepcopy(config or DEFAULT_CONFIG),
        "n": (config or DEFAULT_CONFIG).get("n", 10),
        "initial": [],
        "target": [],
        "frames": [],
        "summary": {
            "status": "invalid",
            "message": "参数无效。",
            "planned_success": False,
            "target_count": 0,
            "initial_count": 0,
            "remaining": 0,
            "filled": 0,
            "total_batches": 0,
            "executed_batches": 0,
            "total_moves": 0,
            "simulated_time": 0.0,
            "losses": 0,
            "pickup_failures": 0,
            "putdown_losses": 0,
            "vacuum_losses": 0,
            "collision_losses": 0,
            "overlap_lost_atoms": 0,
            "empty_moves": 0,
            "tweezer_count": ((config or DEFAULT_CONFIG).get("tweezer_count", 4)
                              if (config or DEFAULT_CONFIG).get("algorithm", "parallel") in MULTI_TWEEZER_ALGORITHMS else 1),
            "max_active_tweezers": 0,
            "collision_checked_batches": 0,
            "native_batches": 0,
        },
    }


def _validate_config(config: Any) -> tuple[dict[str, Any], str | None]:
    if config is None:
        config = {}
    if not isinstance(config, dict):
        return dict(DEFAULT_CONFIG), "参数必须以对象形式提供。"
    values = dict(DEFAULT_CONFIG)
    # Keep only the documented interface, so all returned data remain JSON-safe.
    values.update({key: config[key] for key in DEFAULT_CONFIG if key in config})
    clean = dict(DEFAULT_CONFIG)
    for key, low, high, label in [
        ("n", 4, 24, "阵列边长"),
        ("seed", 0, 2**32 - 1, "随机种子"),
        ("target_size", 1, 24, "目标边长"),
        ("tweezer_count", 1, MAX_TWEEZERS, "同时激活光镊数量上限"),
    ]:
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return clean, f"{label}必须为整数，范围为 {low}–{high}。"
        if not low <= value <= high or not math.isfinite(value) or int(value) != value:
            return clean, f"{label}必须为整数，范围为 {low}–{high}。"
        clean[key] = int(value)
    if clean["target_size"] > clean["n"]:
        return clean, "目标边长不能超过阵列边长。"
    for key, low, high, label in [
        ("loading_prob", 0, 1, "装载概率"),
        ("speed", 0.001, 1, "光镊速度（µm/µs）"),
        ("spacing_um", 1, 20, "阵列间距（µm）"),
        ("lifetime", 0.001, 3600, "原子寿命（秒）"),
        ("pickup_success", 0, 100, "拾取成功率（%）"),
        ("putdown_success", 0, 100, "放下成功率（%）"),
        ("pickup_time_us", 0, 10000, "拾取耗时（µs）"),
        ("putdown_time_us", 0, 10000, "放下耗时（µs）"),
        ("accel_time_us", 0, 10000, "加速耗时（µs）"),
        ("decel_time_us", 0, 10000, "减速耗时（µs）"),
    ]:
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return clean, f"{label}必须在 {low}–{high} 之间。"
        if not low <= value <= high or not math.isfinite(value):
            return clean, f"{label}必须在 {low}–{high} 之间。"
        clean[key] = float(value)
    if not isinstance(values["noise"], bool):
        return clean, "误差开关必须为布尔值。"
    clean["noise"] = values["noise"]
    if not isinstance(values["algorithm"], str) or values["algorithm"] not in ALGORITHMS:
        return clean, "请选择界面提供的原生单物种重排算法。"
    if not isinstance(values["pattern"], str) or values["pattern"] not in PATTERNS:
        return clean, "请选择中心方阵、棋盘格、横条纹或竖条纹目标。"
    clean["algorithm"] = values["algorithm"]
    clean["pattern"] = values["pattern"]
    if clean["pattern"] not in SUPPORTED_PATTERNS_BY_ALGORITHM[clean["algorithm"]]:
        return clean, f"{ALGORITHM_NAMES[clean['algorithm']]} 在本演示中仅支持中心方阵目标。"
    if not isinstance(values["initial_mode"], str) or values["initial_mode"] not in ("random", "manual"):
        return clean, "初始阵列模式必须为 random 或 manual。"
    clean["initial_mode"] = values["initial_mode"]
    if clean["initial_mode"] == "manual":
        matrix = values["initial_matrix"]
        n = clean["n"]
        if not isinstance(matrix, list) or len(matrix) != n:
            return clean, f"手动初始阵列必须为 {n}×{n} 的二维 0/1 列表。"
        normalized = []
        for row in matrix:
            if not isinstance(row, list) or len(row) != n:
                return clean, f"手动初始阵列的每一行必须包含 {n} 个 0/1 值。"
            if any(isinstance(cell, bool) or not isinstance(cell, (int, float)) or cell not in (0, 1) for cell in row):
                return clean, "手动初始阵列只能包含数值 0 或 1。"
            normalized.append([int(cell) for cell in row])
        clean["initial_matrix"] = normalized
    return clean, None


def _matrix_list(matrix: np.ndarray) -> list[list[int]]:
    return matrix[:, :, 0].astype(int).tolist()


def _operation_times(config: dict[str, Any]) -> dict[str, float]:
    """UI microseconds become native seconds, independent of noise sampling."""
    return {f"{operation}_time": config[f"{operation}_time_us"] * 1e-6
            for operation in ("pickup", "putdown", "accel", "decel")}


def _make_initial_array(config: dict[str, Any]) -> tuple[AtomArray, np.random.SeedSequence]:
    """Build one shared initial state and target for both preview and execution."""
    loading_seed, error_seed = np.random.SeedSequence(config["seed"]).spawn(2)
    params = PhysicalParams(
        AOD_speed=config["speed"],
        spacing=config["spacing_um"] * 1e-6,
        loading_prob=config["loading_prob"],
    )
    array = AtomArray([config["n"], config["n"]], params=params,
                      error_model=ZeroNoise(**_operation_times(config)))
    if config["initial_mode"] == "manual":
        array.matrix = np.asarray(config["initial_matrix"], dtype=np.uint8)[:, :, None].copy()
    else:
        array.matrix = random_loading(
            array.shape, config["loading_prob"], rng=np.random.default_rng(loading_seed)
        )[:, :, None]
    array.last_loaded_config = array.matrix.copy()
    array.generate_target(PATTERNS[config["pattern"]], [config["target_size"]] * 2)
    return array, error_seed


def _initial_result(config: dict[str, Any], array: AtomArray) -> dict[str, Any]:
    result = _empty_result(config)
    result["initial"] = _matrix_list(array.matrix)
    result["target"] = _matrix_list(array.target)
    summary = result["summary"]
    summary["initial_count"] = summary["remaining"] = int(array.matrix.sum())
    summary["target_count"] = int(array.target.sum())
    summary["filled"] = int((array.matrix * array.target).sum())
    return result


def preview(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a lightweight initial-array preview, without algorithms or workers.

    Manual mode requires an explicit n×n numeric 0/1 list. To enter manual
    editing from a random state, use preview(random_config)["initial"] first.
    """
    clean, validation_error = _validate_config(config)
    result = _empty_result(clean)
    result["preview"] = True
    if validation_error:
        result["summary"]["message"] = validation_error
        return result
    try:
        array, _ = _make_initial_array(clean)
        result = _initial_result(clean, array)
        result["preview"] = True
        summary = result["summary"]
        summary["status"] = "preview"
        summary["message"] = (
            f"初始阵列预览：{summary['initial_count']} 个原子，"
            f"目标已填充 {summary['filled']}/{summary['target_count']}。点击「运行仿真」生成轨迹。"
        )
    except Exception as error:
        result["summary"]["status"] = "algorithm_error"
        result["summary"]["message"] = f"无法生成初始阵列预览：{type(error).__name__}: {error}。"
    return result


def _simulate_core(
    config: dict[str, Any], emit: Callable[[str, Any], None] | None = None
) -> dict[str, Any]:
    """Run a validated configuration; process limits are applied by simulate()."""
    result = _empty_result(config)
    summary = result["summary"]
    try:
        planner, error_seed = _make_initial_array(config)
        params = planner.params
        initial = planner.matrix.copy()
        target = planner.target.copy()
        result = _initial_result(config, planner)
        summary = result["summary"]
        summary["status"] = "incomplete"
        summary["message"] = "正在生成移动计划。"
        if emit:
            emit("initial", copy.deepcopy(result))
        if summary["initial_count"] < summary["target_count"]:
            summary["status"] = "insufficient"
            suggestion = ("请点击阵列补充原子或缩小目标后重试。"
                          if config["initial_mode"] == "manual" else
                          "请提高装载概率、缩小目标，或更换随机种子后重试。")
            summary["message"] = (
                f"初始只有 {summary['initial_count']} 个原子，目标需要 {summary['target_count']} 个。"
                + suggestion
            )
            return result
        if summary["filled"] == summary["target_count"]:
            summary["status"] = "success"
            summary["planned_success"] = True
            summary["message"] = "初始状态已填满目标，无需移动。"
            return result
        planning_options = {"do_ejection": False}
        if config["algorithm"] == "lbap":
            # The native LBAP wrapper defaults to target_count rounds, which
            # prematurely stops small targets with distant atoms. Use its
            # existing round_lim option, matching ParallelHungarian's minimum.
            planning_options["round_lim"] = max(15, summary["target_count"])
        _, native_moves, planned_success = ALGORITHMS[config["algorithm"]]().get_moves(
            copy.deepcopy(planner), **planning_options
        )
        summary["planned_success"] = bool(planned_success)
        summary["native_batches"] = len(native_moves)
        if len(native_moves) > MAX_BATCHES or sum(len(batch) for batch in native_moves) > MAX_PLANNED_MOVES:
            raise RuntimeError("移动计划超出演示资源限制，请缩小阵列或目标")
        protect_pickup_failures = config["noise"] and config["pickup_success"] < 100
        schedule = schedule_moves(
            planner, native_moves, summary["tweezer_count"],
            protect_pickup_failures=protect_pickup_failures,
            max_batches=MAX_BATCHES, max_moves=MAX_PLANNED_MOVES,
        )
        moves = schedule.batches
        summary["total_batches"] = len(moves)
        summary["collision_checked_batches"] = len(moves)
        summary["skipped_empty_native_batches"] = schedule.skipped_empty_batches
        if emit:
            emit("summary", copy.deepcopy(summary))
        replay_seed = int(error_seed.generate_state(1, dtype=np.uint64)[0])
        if config["noise"]:
            error_model = RecordingErrorModel(
                lifetime=config["lifetime"],
                pickup_fail_rate=1 - config["pickup_success"] / 100,
                putdown_fail_rate=1 - config["putdown_success"] / 100,
                seed=replay_seed,
                **_operation_times(config),
            )
        else:
            error_model = ZeroNoise(seed=replay_seed, **_operation_times(config))
        array = RecordingAtomArray(planner.shape, params=params, error_model=error_model)
        array.matrix = initial.copy()
        array.target = target.copy()
        for index, batch in enumerate(moves):
            safe, reason, _, _ = check_batch(
                array, batch, summary["tweezer_count"],
                protect_pickup_failures=protect_pickup_failures,
                expected_sources={source(move) for move in batch if move.expected_occupied},
            )
            if not safe:
                summary["status"] = "blocked"
                summary["message"] = (
                    f"避碰安全停止：第 {index + 1} 批当前占据不满足安全条件（{reason}）。"
                    f"已保留 {summary['executed_batches']} 批完成状态，未强行搬运或自动重试。"
                )
                return result
            before = _matrix_list(array.matrix)
            _, duration = array.move_atoms(
                batch,
                moves[index - 1] if index else [],
                moves[index + 1] if index + 1 < len(moves) else [],
            )
            serialized_moves = []
            for move_index, move in enumerate(array.applied_moves, 1):
                event = FailureEvent(int(move.fail_event))
                serialized_moves.append({
                    "from": [int(move.from_row), int(move.from_col)],
                    "to": [int(move.to_row), int(move.to_col)],
                    "event": int(event),
                    "event_name": event.name,
                    "flag": int(move.fail_flag),
                    "tweezer_id": int(getattr(move, "tweezer_id", move_index)),
                    "ghost": not bool(before[move.from_row][move.from_col]),
                })
                if event == FailureEvent.PICKUP_FAIL:
                    summary["pickup_failures"] += 1
                elif event == FailureEvent.PUTDOWN_FAIL:
                    summary["putdown_losses"] += 1
                elif event in (FailureEvent.COLLISION_INEVITABLE, FailureEvent.COLLISION_AVOIDABLE):
                    summary["collision_losses"] += 1
                elif event == FailureEvent.NO_ATOM:
                    summary["empty_moves"] += 1
            vacuum_losses = getattr(error_model, "vacuum_losses", [])
            summary["vacuum_losses"] += len(vacuum_losses)
            summary["overlap_lost_atoms"] += array.overlap_lost_atoms
            summary["collision_losses"] += array.overlap_lost_atoms
            summary["simulated_time"] += float(duration)
            summary["executed_batches"] += 1
            summary["total_moves"] += len(serialized_moves)
            summary["remaining"] = int(array.matrix.sum())
            summary["filled"] = int((array.matrix * target).sum())
            summary["losses"] = summary["initial_count"] - summary["remaining"]
            summary["max_active_tweezers"] = max(summary["max_active_tweezers"], len(serialized_moves))
            frame = {
                "before": before,
                "after": _matrix_list(array.matrix),
                "moves": serialized_moves,
                "vacuum_losses": copy.deepcopy(vacuum_losses),
                "overlap_losses": copy.deepcopy(array.overlap_losses),
                "elapsed": summary["simulated_time"],
                "duration": float(duration),
                "active_tweezers": len(serialized_moves),
                "collision_checked": True,
                "native_batch": schedule.native_indices[index] + 1,
                "counts": {key: summary[key] for key in (
                    "remaining", "filled", "losses", "pickup_failures", "putdown_losses",
                    "vacuum_losses", "collision_losses",
                )},
            }
            result["frames"].append(frame)
            if emit:
                emit("frame", (frame, copy.deepcopy(summary)))
        if schedule.blocked_reason:
            summary["status"] = "blocked"
            summary["message"] = (
                f"避碰安全停止：{schedule.blocked_reason}。"
                f"已保留 {summary['executed_batches']} 批完成状态，目标填充 "
                f"{summary['filled']}/{summary['target_count']}，未自动重规划。"
            )
        elif summary["filled"] == summary["target_count"]:
            summary["status"] = "success"
            summary["message"] = f"目标已填满：{summary['filled']}/{summary['target_count']}。"
        else:
            summary["status"] = "incomplete"
            reason = ("原计划在误差与损耗条件下未填满目标"
                      if config["noise"] else "原算法未完全填满目标")
            summary["message"] = (
                f"按原计划执行完成，目标填充 {summary['filled']}/{summary['target_count']}；"
                f"{reason}，本次未自动补齐。"
            )
    except Exception as error:
        summary["status"] = "algorithm_error"
        summary["message"] = (
            f"原算法或模拟执行失败：{type(error).__name__}: {error}。"
            "已保留完成的步骤，可调整参数后重试。"
        )
    return result


def _simulation_worker(config: dict[str, Any], connection) -> None:
    try:
        result = _simulate_core(config, lambda kind, payload: connection.send((kind, payload)))
        connection.send(("done", result["summary"]))
    except BaseException as error:
        try:
            connection.send(("worker_error", f"{type(error).__name__}: {error}"))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()


def simulate(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return JSON-safe simulation data, with a bounded macOS-safe worker process."""
    clean, validation_error = _validate_config(config)
    result = _empty_result(clean)
    if validation_error:
        result["summary"]["message"] = validation_error
        return result
    receiver = sender = worker = None
    deadline = time.monotonic() + SIMULATION_TIMEOUT_SECONDS
    complete = False
    error_message = None
    try:
        context = mp.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        worker = context.Process(target=_simulation_worker, args=(clean, sender))
        worker.start()
        sender.close()
        while time.monotonic() < deadline:
            if receiver.poll(min(0.1, max(0, deadline - time.monotonic()))):
                try:
                    kind, payload = receiver.recv()
                except EOFError:
                    break
                if kind == "initial":
                    result = payload
                elif kind == "summary":
                    result["summary"] = payload
                elif kind == "frame":
                    frame, summary = payload
                    result["frames"].append(frame)
                    result["summary"] = summary
                elif kind == "done":
                    result["summary"] = payload
                    complete = True
                    break
                elif kind == "worker_error":
                    error_message = payload
                    break
            elif not worker.is_alive():
                break
        if not complete:
            result["summary"]["status"] = "algorithm_error"
            if error_message:
                result["summary"]["message"] = f"模拟进程失败：{error_message}。已保留完成的步骤。"
            elif time.monotonic() >= deadline:
                result["summary"]["message"] = (
                    f"计算超过 {SIMULATION_TIMEOUT_SECONDS:g} 秒，已停止并保留完成的步骤。"
                    "请缩小阵列或目标后重试。"
                )
            else:
                result["summary"]["message"] = "模拟进程提前退出，已保留完成的步骤。请重新运行。"
    except Exception as error:
        result["summary"]["status"] = "algorithm_error"
        result["summary"]["message"] = f"无法启动模拟进程：{type(error).__name__}: {error}。"
    finally:
        if worker is not None and worker.pid is not None:
            if worker.is_alive() and not complete:
                worker.terminate()
            worker.join(timeout=1)
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=1)
            worker.close()
        if receiver is not None:
            receiver.close()
        if sender is not None:
            sender.close()
    return result
