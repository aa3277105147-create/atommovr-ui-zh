"""Local Chinese controls for the downloaded atommovr simulator."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import time
import urllib.request
import webbrowser

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
os.environ.setdefault("MPLBACKEND", "Agg")

import gradio as gr

from simulator import (DEFAULT_CONFIG, ALGORITHM_NAMES, ALGORITHM_PATTERNS,
                       MULTI_TWEEZER_ALGORITHMS, MAX_TWEEZERS, preview, simulate)
from comparison import TABLE_HEADERS, compare_algorithms
from benchmark import HEADERS as BENCHMARK_HEADERS, MAX_TRIALS, benchmark_algorithms, export_csv
from version import __version__

HERE = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("ATOMMOVR_UI_STATE_DIR", HERE / ".runtime")).expanduser()
KEYS = ["n", "target_size", "loading_prob", "seed", "algorithm", "pattern",
        "speed", "spacing_um", "noise", "lifetime", "pickup_success", "putdown_success", "initial_mode", "tweezer_count",
        "pickup_time_us", "putdown_time_us", "accel_time_us", "decel_time_us"]
PATTERNS = [("中心方阵", "center"), ("棋盘格", "checkerboard"),
            ("横向条纹", "horizontal"), ("纵向条纹", "vertical")]
ALGORITHMS = [(name, key) for key, name in ALGORITHM_NAMES.items()]
ALGORITHM_INFO = {
    "parallel": "距离成本匹配后进行并行调度。支持四种目标；匹配成本与实际搬运时间是不同指标。",
    "hungarian": "距离成本匹配后顺序搬运。支持四种目标；避障与中间搬运可能增加实际路程。",
    "lbap": "实验实现：优先降低最长匹配距离。原生并行计划有已知碰撞问题，本界面采用单光镊保守执行；以实际填充结果为准。",
    "generalized": "递归交替进行行、列占用平衡。支持四种目标；适合与匹配类算法比较搬运批次。",
    "bcv2": "优化的平衡与中心压缩实现，可批量搬运。仅支持中心方阵。",
    "bc": "传统平衡与中心压缩实现。仅支持中心方阵；用于与优化版本比较。",
}

CSS = """
body { background:#eceef0 !important; }
.gradio-container { width:100% !important; max-width:1440px !important; margin:auto !important;
    font-family:Arial,-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif !important; }
#hero { padding:12px 2px 8px; border-bottom:1px solid #bdc4cc; margin-bottom:10px; }
#hero h1 { font-size:23px; font-weight:600; color:#222b34; margin:0 0 6px; }
#hero p { color:#56616d; font-size:13px; line-height:1.6; margin:0; }
#controls { background:#f7f8fa; padding:16px; border:1px solid #bcc4cc;
    border-radius:3px; gap:10px; box-shadow:none; }
#controls h2 { font-size:15px; color:#222b34; margin:0; border-bottom:1px solid #c8ced5; padding-bottom:8px; }
#controls .gradio-slider, #controls .gradio-number, #controls .gradio-dropdown,
#controls .gradio-checkbox { box-shadow:none; }
#controls input { accent-color:#0072bd; }
#controls button.primary { background:#0072bd !important; border-color:#005d9b !important; }
#controls button { min-height:35px; border-radius:3px; font-size:13px; }
#controls input, #controls .wrap, #controls .form { border-radius:3px !important; }
#parameter-status p { font-size:12px; line-height:1.6; margin:0; }
#control-note p { font-size:12px; color:#74858e; line-height:1.6; }
#initial-note p { font-size:12px; color:#526171; line-height:1.5; }
#algorithm-note p, #tweezer-note p { font-size:12px; color:#526171; line-height:1.5; margin:0; }
#comparison-panel, #reference-panel, #benchmark-panel { border:1px solid #bcc4cc; border-radius:3px; background:#f7f8fa; }
#comparison-status p { font-size:12px; line-height:1.6; }
#comparison-table, #benchmark-table { min-width:0; max-width:100%; }
#comparison-table th, #benchmark-table th { white-space:nowrap !important; word-break:normal !important; }
#algorithm-reference { overflow-x:auto; font-size:12px; }
#presets { gap:8px; }
#page-note p { color:#63717e; font-size:11px; text-align:center; line-height:1.6; }
@media (max-width:720px) {
  .gradio-container { padding:12px !important; }
  #hero { padding:8px 2px 4px; }
  #hero h1 { font-size:20px; }
  #controls { padding:12px; }
}
"""


def as_config(values, layout=None):
    config = dict(zip(KEYS, values))
    for key in ("n", "target_size", "seed", "tweezer_count"):
        value = config[key]
        if isinstance(value, (int, float)) and float(value).is_integer():
            config[key] = int(value)
    if isinstance(config.get("n"), int) and isinstance(config.get("target_size"), int):
        config["target_size"] = min(config["n"], config["target_size"])
    allowed = ALGORITHM_PATTERNS.get(config.get("algorithm"), ())
    if allowed and config.get("pattern") not in allowed:
        config["pattern"] = allowed[0]
    if config.get("algorithm") not in MULTI_TWEEZER_ALGORITHMS:
        config["tweezer_count"] = 1
    config["initial_matrix"] = None
    if config.get("initial_mode") == "manual":
        matrix = (layout or {}).get("matrix", [])
        n = config.get("n", 10)
        if isinstance(n, int) and 4 <= n <= 24:
            config["initial_matrix"] = [[matrix[r][c] if r < len(matrix) and c < len(matrix[r]) else 0
                                         for c in range(n)] for r in range(n)]
    return config


def show_preview(*args):
    config = as_config(args[:-1], args[-1])
    result = preview(config)
    layout = ({"n": result["n"], "matrix": result["initial"]}
              if result["initial"] else args[-1])
    prefix = "**初态预览 / 参数已修改**" if result['summary']['status'] == 'preview' else "**参数或预览异常**"
    return result, layout, prefix + " · " + result["summary"]["message"]


def capture_request(*args):
    return as_config(args[:-1], args[-1])


def refresh_preview(*args):
    """A delayed input refresh must not overwrite a completed matching run."""
    values, layout, result = args[:-2], args[-2], args[-1]
    if result and as_config(values, layout) == result.get("config"):
        status = result.get('summary', {}).get('status')
        note = "**仿真已计算** · 点击「播放」或单步查看搬运过程。" if status in ('success', 'incomplete') else "**请调整参数** · " + result.get('summary', {}).get('message', '')
        return gr.skip(), gr.skip(), note
    return show_preview(*values, layout)


def run_simulation(config):
    try:
        result = simulate(config)
    except Exception:
        result = {
            "config": config, "n": config.get("n", 10), "initial": [], "target": [],
            "frames": [], "summary": {"status": "algorithm_error",
                "message": "本次仿真未能完成，请检查参数后重试。", "initial_count": 0,
                "target_count": 0, "remaining": 0, "filled": 0,
                "total_batches": 0, "executed_batches": 0, "total_moves": 0,
                "simulated_time": 0, "planned_success": False},
        }
    return result


def begin_run():
    return gr.Button(interactive=False), "**正在计算** · 准备本次原子搬运轨迹…"


def publish_result(*args):
    values, layout, result = args[:-2], args[-2], args[-1]
    config = as_config(values, layout)
    if config != result.get("config"):
        shown, layout, status = show_preview(*values, layout)
        status = "**计算期间参数已修改** · 已显示最新初态预览，请重新运行。"
    else:
        shown = result
        layout = {"n": result["n"], "matrix": result["initial"]}
        failed = result["summary"]["status"] in {"invalid", "algorithm_error", "insufficient", "blocked"}
        status = ("**请调整参数** · " + result["summary"]["message"] if failed
                  else "**仿真已计算** · 点击「播放」或单步查看搬运过程。")
    return shown, layout, status, gr.Button(interactive=True)


def edit_initial(n, target_size, loading_prob, seed, algorithm, pattern, speed,
                 spacing_um, noise, lifetime, pickup_success, putdown_success,
                 initial_mode, tweezer_count, pickup_time_us, putdown_time_us,
                 accel_time_us, decel_time_us, layout, evt: gr.EventData):
    # Gradio injects EventData into positional parameters, not keyword-only args.
    values = [n, target_size, loading_prob, seed, algorithm, pattern, speed,
              spacing_um, noise, lifetime, pickup_success, putdown_success, initial_mode, tweezer_count,
              pickup_time_us, putdown_time_us, accel_time_us, decel_time_us]
    config = as_config(values, layout)
    matrix = evt._data.get("matrix") if isinstance(evt._data, dict) else None
    if config["initial_mode"] == "manual" and isinstance(matrix, list) and len(matrix) == config["n"]:
        edited = dict(config, initial_matrix=matrix)
        checked = preview(edited)
        if checked["summary"]["status"] == "preview":
            return checked, {"n": checked["n"], "matrix": checked["initial"]}, "**手动初态已更新** · 点击网格添加或移除原子，点击「运行仿真」计算轨迹。"
    return show_preview(*values, layout)


def clear_initial(*args):
    values = args[:-1]
    n = int(values[0])
    return show_preview(*values, {"n": n, "matrix": [[0] * n for _ in range(n)]})


def preset(kind):
    config = dict(DEFAULT_CONFIG)
    if kind == "loss":
        config.update(noise=True, speed=0.001, lifetime=0.01,
                      pickup_success=90, putdown_success=90)
    return [config[k] for k in KEYS]


def resize_target(n, target_size):
    return gr.Slider(maximum=int(n), value=min(int(n), int(target_size)))


def constrain_pattern(algorithm, pattern):
    choices = [p for p in PATTERNS if p[1] in ALGORITHM_PATTERNS.get(algorithm, ())]
    value = pattern if any(p[1] == pattern for p in choices) else choices[0][1]
    return gr.Dropdown(choices=choices, value=value)


def algorithm_note(algorithm):
    return ALGORITHM_INFO.get(algorithm, "请选择算法。")


def tweezer_note(algorithm):
    if algorithm in MULTI_TWEEZER_ALGORITHMS:
        return "支持数量受限的多光镊调度。检查 AOD 轨迹冲突与占用，冲突或超出数量的动作分批执行；空位交点也计入光镊数量。"
    return "该算法在本界面使用单光镊执行，数量固定为 1。移动路径仍需检查，无法安全执行时会停止并说明原因。"


def constrain_tweezers(algorithm, count):
    enabled = algorithm in MULTI_TWEEZER_ALGORITHMS
    value = max(1, min(MAX_TWEEZERS, int(count or 1))) if enabled else 1
    return gr.Slider(value=value, interactive=enabled), tweezer_note(algorithm)


def begin_comparison():
    return gr.Button(interactive=False), "**正在对比** · 使用同一初态逐一计算，期间仍可调整参数和查看动画。"


def comparison_note(*args):
    values, layout, result = args[:-2], args[-2], args[-1]
    if not result:
        return "尚未对比。按当前参数冻结初态，逐一运行支持所选图案的算法。"
    config = result.get("config", {})
    unchanged = as_config(values, layout) == config
    prefix = "**对比已完成**" if unchanged else "**参数已修改，请重新对比** · 下表保留上次对比快照"
    pattern = dict((value, label) for label, value in PATTERNS).get(config.get("pattern"), "")
    if config.get("pattern") == "center":
        pattern += f" {config.get('target_size')}×{config.get('target_size')}"
    atoms = sum(sum(row) for row in result.get("initial_matrix", []))
    context = f"{config.get('n')}×{config.get('n')} 阵列，{pattern}，初始 {atoms} 个原子，种子 {config.get('seed')}，光镊上限 {config.get('tweezer_count', 1)}，" + ("启用误差" if config.get("noise") else "理想模式")
    if result.get("status") == "invalid":
        return "**对比参数无效** · " + result.get("message", "请调整参数。")
    return prefix + " · " + context + "。\n\n" + result.get("footnote", "")


def publish_comparison(*args):
    result = args[-1] or {}
    return result.get("table_rows", []), comparison_note(*args), gr.Button(interactive=True)


def benchmark_note(*args):
    values, layout, trials, result = args[:-3], args[-3], args[-2], args[-1]
    if not result:
        return "尚未统计。每次试验中，各算法使用相同初态；原子不足和安全停止也计入试验总数。"
    unchanged = as_config(values, layout) == result.get("config") and trials == result.get("trials")
    prefix = "" if unchanged else "**设置已修改，以下为上次统计快照。** "
    config = result.get("config", {})
    mode = "每次重新随机装载" if config.get("initial_mode") == "random" else "固定手动初态，仅改变误差种子"
    return prefix + result.get("message", "") + f" 起始种子 {config.get('seed')}，{mode}。"


def capture_benchmark(*args):
    return {"config": as_config(args[:-2], args[-2]), "trials": args[-1]}


def run_benchmark(request, progress=gr.Progress()):
    return benchmark_algorithms(request["config"], request["trials"], on_progress=progress)


def publish_benchmark(*args):
    result = args[-1] or {}
    path = export_csv(result, STATE_DIR / "exports")
    return result.get("rows", []), benchmark_note(*args), gr.Button(interactive=True), gr.DownloadButton(value=path, interactive=bool(path))


def refresh_notes(*args):
    inputs, trials, compared, benchmarked = args[:-3], args[-3], args[-2], args[-1]
    return comparison_note(*inputs, compared), benchmark_note(*inputs, trials, benchmarked)


def build_app():
    initial_preview = preview(DEFAULT_CONFIG)
    with gr.Blocks(title="atommovr · 原子重排演示", analytics_enabled=False, fill_width=True) as demo:
        gr.Markdown(f"# atommovr · 原子重排实验台 v{__version__}\n初态与目标实时预览 → 运行仿真 → 播放搬运轨迹　|　单物种光镊阵列", elem_id="hero")
        layout_state = gr.State({"n": 10, "matrix": initial_preview["initial"]})
        request_state = gr.State(dict(DEFAULT_CONFIG))
        result_state = gr.State(None)
        comparison_request = gr.State(None)
        comparison_result = gr.State(None)
        benchmark_request = gr.State(None)
        benchmark_result = gr.State(None)
        with gr.Row(equal_height=False):
            with gr.Column(scale=1, min_width=310, elem_id="controls"):
                gr.Markdown("## 参数 / Parameters")
                with gr.Row(elem_id="presets"):
                    ideal = gr.Button("理想重排", size="sm", min_width=100)
                    lossy = gr.Button("明显损耗", size="sm", min_width=100)
                algorithm = gr.Dropdown(ALGORITHMS, value="parallel", label="重排算法", filterable=False)
                algorithm_info = gr.Markdown(algorithm_note("parallel"), elem_id="algorithm-note")
                tweezer_count = gr.Slider(1, MAX_TWEEZERS, value=DEFAULT_CONFIG["tweezer_count"], step=1,
                                         label="移动光镊数量", info="同时激活的光镊上限，含空位交点")
                tweezer_info = gr.Markdown(tweezer_note("parallel"), elem_id="tweezer-note")
                pattern = gr.Dropdown(PATTERNS, value="center", label="目标图案", filterable=False)
                n = gr.Slider(4, 24, value=10, step=1, label="阵列边长", info="N × N 个光镊位置")
                target_size = gr.Slider(1, 10, value=4, step=1, label="中心目标边长", info="仅中心方阵使用此参数")
                loading_prob = gr.Slider(0, 1, value=.6, step=.01, label="原子装载概率")
                seed = gr.Number(value=DEFAULT_CONFIG["seed"], precision=0, minimum=0, maximum=2**32-1, label="随机种子", info="相同参数与种子可复现相同结果")
                initial_mode = gr.Dropdown([("随机装载（实验初态）", "random"), ("手动布置（指定初态）", "manual")],
                                           value="random", label="初始原子分布", filterable=False)
                gr.Markdown("参数变化后右图实时预览。手动模式下，点击网格位置添加或移除原子；改变阵列尺寸时保留仍在范围内的位置。", elem_id="initial-note")
                with gr.Row(visible=False) as edit_tools:
                    edit_view = gr.Button("编辑初态", size="sm", min_width=80)
                    clear = gr.Button("清空布置", size="sm", min_width=80)
                with gr.Accordion("物理与误差参数", open=False):
                    speed = gr.Slider(.001, 1, value=.1, step=.001, label="光镊移动速度（µm/µs）")
                    spacing_um = gr.Slider(1, 20, value=5, step=.1, label="阵列间距（µm）")
                    with gr.Accordion("操作耗时（进阶）", open=False):
                        pickup_time_us = gr.Number(value=0, minimum=0, maximum=10000, label="拾取耗时（µs）")
                        putdown_time_us = gr.Number(value=0, minimum=0, maximum=10000, label="放下耗时（µs）")
                        accel_time_us = gr.Number(value=0, minimum=0, maximum=10000, label="加速耗时（µs）")
                        decel_time_us = gr.Number(value=0, minimum=0, maximum=10000, label="减速耗时（µs）")
                        gr.Markdown("连续搬运按相邻动作规则合并操作耗时。关闭误差时这些耗时仍生效；加减速参数为附加时间，不模拟速度曲线。")
                    noise = gr.Checkbox(value=False, label="启用误差与原子损耗")
                    lifetime = gr.Number(value=30, minimum=.001, maximum=3600, label="原子寿命（秒）", interactive=False)
                    pickup_success = gr.Slider(0, 100, value=99, step=.1, label="拾取成功率（%）", interactive=False)
                    putdown_success = gr.Slider(0, 100, value=99, step=.1, label="放下成功率（%）", interactive=False)
                    gr.Markdown("「明显损耗」使用刻意放大的教学参数。播放慢放与暂停不会增加模拟损耗。", elem_id="control-note")
                run = gr.Button("运行仿真", variant="primary", interactive=False)
                new_seed = gr.Button("换一份随机分布")
                parameter_status = gr.Markdown("⏳ 正在准备默认演示…", elem_id="parameter-status")
            with gr.Column(scale=2, min_width=320):
                player = gr.HTML(
                    value=initial_preview,
                    html_template=(HERE / "player.html").read_text(),
                    css_template=(HERE / "player.css").read_text(),
                    js_on_load=(HERE / "player.js").read_text(),
                    apply_default_css=False,
                    elem_id="atom-player", padding=False,
                )
        with gr.Accordion("算法对照实验 · 单次运行", open=False, elem_id="comparison-panel"):
            gr.Markdown("观察不同算法如何处理同一个原子阵列。各算法使用相同初态、目标与物理条件；本表描述单个场景，可结合下方多次统计了解结果的波动。")
            compare = gr.Button("对比全部可用算法", size="sm")
            comparison_status = gr.Markdown("尚未对比。按当前参数冻结初态，逐一运行支持所选图案的算法。", elem_id="comparison-status")
            comparison_table = gr.Dataframe(value=[], headers=TABLE_HEADERS,
                                           datatype=["str", "str", "str"] + ["number"] * (len(TABLE_HEADERS) - 3),
                                           interactive=False, wrap=False, column_widths=[240, 130, 150, 100, 120, 100, 130, 190, 200],
                                           elem_id="comparison-table", max_height=420, show_row_numbers=False, show_label=False, type="array", buttons=["copy", "fullscreen"])
        with gr.Accordion("算法对照实验 · 多次统计", open=False, elem_id="benchmark-panel"):
            gr.Markdown("使用连续随机种子重复试验，观察填充比例、损失与成功运行的耗时。随机模式每次重新装载；手动模式保留同一布置。关闭误差时，手动布置的重复结果相同。")
            trials = gr.Slider(1, MAX_TRIALS, value=5, step=1, label="每种算法的试验次数")
            with gr.Row():
                benchmark_run = gr.Button("运行多次统计", size="sm")
                benchmark_download = gr.DownloadButton("下载逐次结果 CSV", interactive=False, size="sm")
            benchmark_status = gr.Markdown(benchmark_note(*[DEFAULT_CONFIG[k] for k in KEYS], None, 5, None))
            benchmark_table = gr.Dataframe(value=[], headers=BENCHMARK_HEADERS, datatype="str", interactive=False,
                                          wrap=False, column_widths=[240, 110, 170, 150, 160, 200, 140, 220],
                                          elem_id="benchmark-table", max_height=420, show_row_numbers=False, show_label=False, type="array", buttons=["copy", "fullscreen"])
            gr.Markdown("全部填满比例 = 最终目标全部占据的试验数 / 已执行试验数。平均填充包含不足、停止和未完成的结果；成功平均时间仅统计全部填满的试验，并列出样本数。失败记录不会因耗时较短而被视为速度优势。各算法的噪声采样顺序不同，结果是有限样本的描述统计。计算约 2 分钟后会停止新增试验，保留已完成记录。")
        with gr.Accordion("算法原理与参考文献", open=False, elem_id="reference-panel"):
            reference = HERE / "算法说明.md"
            gr.Markdown(reference.read_text() if reference.exists() else "算法说明正在整理。", elem_id="algorithm-reference")
        gr.Markdown(
            "单物种演示 · 核心算法与仿真模型来自 "
            "[atommovr](https://github.com/bernienlab/atommovr) · "
            "目标外原子保留 · 误差模式执行一次原计划",
            elem_id="page-note",
        )

        controls = [n, target_size, loading_prob, seed, algorithm, pattern, speed,
                    spacing_um, noise, lifetime, pickup_success, putdown_success, initial_mode, tweezer_count,
                    pickup_time_us, putdown_time_us, accel_time_us, decel_time_us]
        preview_inputs = controls + [layout_state]
        preview_outputs = [player, layout_state, parameter_status]
        gr.on(triggers=[c.input for c in controls], fn=refresh_preview,
              inputs=preview_inputs+[result_state], outputs=preview_outputs,
              trigger_mode="always_last", concurrency_limit=1, concurrency_id="configuration",
              show_progress="hidden", api_visibility="private")
        n.change(resize_target, inputs=[n, target_size], outputs=target_size, queue=False, api_visibility="private")
        algorithm.change(constrain_pattern, inputs=[algorithm, pattern], outputs=pattern, queue=False, api_visibility="private")
        algorithm.change(algorithm_note, algorithm, algorithm_info, queue=False, api_visibility="private")
        algorithm.change(constrain_tweezers, [algorithm, tweezer_count], [tweezer_count, tweezer_info],
                         queue=False, api_visibility="private")
        pattern.change(lambda p: gr.Slider(interactive=p == "center"), pattern, target_size,
                       queue=False, api_visibility="private")
        noise.change(lambda enabled: [gr.Number(interactive=enabled), gr.Slider(interactive=enabled), gr.Slider(interactive=enabled)],
                     inputs=noise, outputs=[lifetime, pickup_success, putdown_success], queue=False, api_visibility="private")
        ideal_event = ideal.click(lambda: preset("ideal"), outputs=controls, queue=False, api_visibility="private").then(
            show_preview, inputs=preview_inputs, outputs=preview_outputs,
            concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        lossy_event = lossy.click(lambda: preset("loss"), outputs=controls, queue=False, api_visibility="private").then(
            show_preview, inputs=preview_inputs, outputs=preview_outputs,
            concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        initial_mode.change(lambda mode: [gr.Slider(interactive=mode == "random"),
                                         gr.Button(interactive=mode == "random"), gr.Row(visible=mode == "manual")],
                            initial_mode, [loading_prob, new_seed, edit_tools], queue=False, api_visibility="private")
        player.edit(edit_initial, inputs=preview_inputs, outputs=preview_outputs,
                    concurrency_limit=1, concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        edit_view.click(show_preview, inputs=preview_inputs, outputs=preview_outputs,
                        concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        clear.click(clear_initial, inputs=preview_inputs, outputs=preview_outputs,
                    concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        seed_event = new_seed.click(lambda: secrets.randbelow(2**32), outputs=seed, queue=False, api_visibility="private").then(
            show_preview, inputs=preview_inputs, outputs=preview_outputs,
            concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        for event in (ideal_event, lossy_event, seed_event):
            event.then(refresh_notes, inputs=preview_inputs+[trials, comparison_result, benchmark_result],
                       outputs=[comparison_status, benchmark_status], concurrency_id="configuration",
                       show_progress="hidden", api_visibility="private")

        compute = run.click(begin_run, outputs=[run, parameter_status], queue=False, api_visibility="private")
        compute = compute.then(capture_request, inputs=preview_inputs, outputs=request_state,
                               concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        compute = compute.then(run_simulation, inputs=request_state, outputs=result_state,
                               api_name="simulate", concurrency_limit=1, concurrency_id="simulation", show_progress="minimal")
        compute.then(publish_result, inputs=preview_inputs+[result_state], outputs=preview_outputs+[run],
                     concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        loaded = demo.load(run_simulation, inputs=request_state, outputs=result_state,
                           concurrency_limit=1, concurrency_id="simulation", show_progress="minimal", api_visibility="private")
        loaded.then(publish_result, inputs=preview_inputs+[result_state], outputs=preview_outputs+[run],
                    concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        gr.on(triggers=[c.input for c in controls]+[layout_state.change], fn=comparison_note,
              inputs=preview_inputs+[comparison_result], outputs=comparison_status, trigger_mode="always_last",
              concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        comparing = compare.click(begin_comparison, outputs=[compare, comparison_status], queue=False, api_visibility="private")
        comparing = comparing.then(capture_request, inputs=preview_inputs, outputs=comparison_request,
                                  concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        comparing = comparing.then(compare_algorithms, inputs=comparison_request, outputs=comparison_result,
                                  concurrency_id="simulation", concurrency_limit=1, show_progress="minimal", api_visibility="private")
        comparing.then(publish_comparison, inputs=preview_inputs+[comparison_result],
                       outputs=[comparison_table, comparison_status, compare],
                       concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        gr.on(triggers=[c.input for c in controls]+[layout_state.change, trials.input], fn=benchmark_note,
              inputs=preview_inputs+[trials, benchmark_result], outputs=benchmark_status, trigger_mode="always_last",
              concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        benchmarking = benchmark_run.click(lambda: [gr.Button(interactive=False), "**正在统计** · 逐次执行相同条件下的算法对照。"],
                                          outputs=[benchmark_run, benchmark_status], queue=False, api_visibility="private")
        benchmarking = benchmarking.then(capture_benchmark, inputs=preview_inputs+[trials], outputs=benchmark_request,
                                         concurrency_id="configuration", show_progress="hidden", api_visibility="private")
        benchmarking = benchmarking.then(run_benchmark, inputs=benchmark_request, outputs=benchmark_result,
                                         concurrency_id="simulation", concurrency_limit=1, show_progress="minimal", api_visibility="private")
        benchmarking.then(publish_benchmark, inputs=preview_inputs+[trials, benchmark_result],
                          outputs=[benchmark_table, benchmark_status, benchmark_run, benchmark_download],
                          concurrency_id="configuration", show_progress="hidden", api_visibility="private")
    return demo


def existing_url():
    try:
        info = json.loads((STATE_DIR / "server.json").read_text())
        url = info["url"]
        if not url.startswith("http://127.0.0.1:"):
            return None
        with urllib.request.urlopen(url + "atommovr-health", timeout=1) as response:
            health = json.load(response)
            if (health.get("application") == "atommovr-ui" and
                    health.get("version") == __version__):
                return url
    except (OSError, ValueError, KeyError):
        pass
    return None


def server_settings():
    """Return the bind address requested by the runtime environment."""
    server_name = os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1").strip() or "127.0.0.1"
    # Gradio's variable is explicit; PORT is the conventional contract used by
    # services such as Render. Local launches leave both unset and let Gradio
    # choose its normal default port.
    port_variable = "GRADIO_SERVER_PORT" if "GRADIO_SERVER_PORT" in os.environ else "PORT"
    raw_port = os.environ.get(port_variable, "").strip()
    if not raw_port:
        return server_name, None
    try:
        server_port = int(raw_port)
    except ValueError as error:
        raise ValueError(f"{port_variable} 必须是 1—65535 之间的整数。") from error
    if not 1 <= server_port <= 65535:
        raise ValueError(f"{port_variable} 必须是 1—65535 之间的整数。")
    return server_name, server_port


def queue_max_size():
    """Keep local capacity convenient while bounding public shared instances."""
    raw_size = os.environ.get("ATOMMOVR_QUEUE_MAX_SIZE", "32").strip()
    try:
        size = int(raw_size)
    except ValueError as error:
        raise ValueError("ATOMMOVR_QUEUE_MAX_SIZE 必须是 1—256 之间的整数。") from error
    if not 1 <= size <= 256:
        raise ValueError("ATOMMOVR_QUEUE_MAX_SIZE 必须是 1—256 之间的整数。")
    return size


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        server_name, server_port = server_settings()
        max_queue = queue_max_size()
    except ValueError as error:
        parser.error(str(error))
    url = existing_url() if server_name in {"127.0.0.1", "localhost"} else None
    if url:
        print("演示界面已运行：" + url, flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("GRADIO_TEMP_DIR", str(STATE_DIR / "cache"))
    demo = build_app().queue(default_concurrency_limit=1, max_size=max_queue)
    theme = gr.themes.Base(primary_hue="blue", secondary_hue="gray", neutral_hue="gray", radius_size="sm", text_size="sm", spacing_size="sm")
    server, url, _ = demo.launch(server_name=server_name, server_port=server_port, share=False,
                               inbrowser=False, prevent_thread_lock=True,
                               theme=theme, css=CSS, footer_links=[], show_error=False,
                               ssr_mode=False)

    @server.get("/atommovr-health")
    def health():
        return {"application": "atommovr-ui", "version": __version__}

    (STATE_DIR / "server.json").write_text(json.dumps({"url": url, "pid": os.getpid()}))
    print("中文演示界面已启动：" + url, flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        demo.close()


if __name__ == "__main__":
    main()
