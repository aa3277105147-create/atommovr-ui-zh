# 第三方项目说明

本仓库新增并实现参数界面、Canvas 播放器、仿真数据适配、数量受限的保守调度、算法对照与统计、导出和跨平台启动工具。本项目不是 atommovr 官方项目，也不捆绑其源码；上述范围不主张上游算法、物理模型或标准匹配与轨迹检查方法的原创性。

六种重排算法、原子阵列模型、误差模型和核心物理计时来自官方 [bernienlab/atommovr](https://github.com/bernienlab/atommovr)。托管下载与参考版本固定到提交 `cca2553985bb9d81b19cae9b83074df4816502f9`；用户指定或自动发现的现有源码可能不同。这些上游内容不属于本项目原创。atommovr 采用 MIT License，版权归 Nikhil K. Harle、Bo-Yu Chen、Bob Bao 和 Hannes Bernien 所有。

论文引用：N. K. Harle, B.-Y. Chen, B. Bao, and H. Bernien, “atommovr: An open-source simulation framework for rearrangement in atomic arrays,” *Quantum* **10**, 2177 (2026). [DOI: 10.22331/q-2026-07-29-2177](https://doi.org/10.22331/q-2026-07-29-2177).

atommovr 的并行 LBAP 实现还会使用其完整源码目录内的 PPSU2023 组件。该组件由上游项目负责分发和构建；本仓库不会提交其源码、预编译库或生成文件。相关来源与许可说明请查阅 atommovr 官方仓库中的 `PPSU2023/README.md`。
