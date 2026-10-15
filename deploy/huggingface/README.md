---
title: atommovr 中文原子重排实验台
emoji: ⚛️
colorFrom: blue
colorTo: teal
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: 基于 atommovr 的中文原子重排交互演示与算法比较平台
---

# atommovr 中文原子重排实验台

这是 [atommovr-ui-zh](https://github.com/aa3277105147-create/atommovr-ui-zh) 的公开在线运行环境。

界面、播放器、调度适配和统计功能由本项目提供；原子阵列模型、误差模型及基础重排算法来自
[bernienlab/atommovr](https://github.com/bernienlab/atommovr)，容器固定使用提交
`cca2553985bb9d81b19cae9b83074df4816502f9`。两个项目均按各自仓库中的许可文件发布。

在线实例使用共享 CPU，空闲后可能休眠。首次打开或重新唤醒时需要等待容器启动。
仿真任务串行执行，公开实例的等待队列最多保留 8 个任务。
