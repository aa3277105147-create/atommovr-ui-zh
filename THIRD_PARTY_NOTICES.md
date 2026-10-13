# 第三方项目说明

本仓库提供独立的中文交互界面、仿真适配层和保守调度层，不是 atommovr 官方项目，也未复制其源码。

运行时依赖官方 [bernienlab/atommovr](https://github.com/bernienlab/atommovr)，固定到提交 `cca2553985bb9d81b19cae9b83074df4816502f9`。atommovr 采用 MIT License，版权归 Nikhil K. Harle、Bo-Yu Chen、Bob Bao 和 Hannes Bernien 所有。

论文引用：N. K. Harle, B.-Y. Chen, B. Bao, and H. Bernien, “atommovr: An open-source simulation framework for rearrangement in atomic arrays,” *Quantum* **10**, 2177 (2026). [DOI: 10.22331/q-2026-07-29-2177](https://doi.org/10.22331/q-2026-07-29-2177).

atommovr 的并行 LBAP 实现还会使用其完整源码目录内的 PPSU2023 组件。该组件由上游项目负责分发和构建；本仓库不会提交其源码、预编译库或生成文件。相关来源与许可说明请查阅 atommovr 官方仓库中的 `PPSU2023/README.md`。
