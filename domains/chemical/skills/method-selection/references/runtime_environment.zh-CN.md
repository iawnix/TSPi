# 执行环境选择

`RESEARCH_AGENT_PYTHON` 是安装管理的控制解释器，用于准备请求和整理已有证据，不提供科学库。

选择已安装的执行入口和 `job.toml` 中的命名环境。入口声明依赖，所选绑定提供目标
Python 或原生程序。结构准备与化学验证器可共用 `structure.lock` 环境；Gaussian/xTB
的 Python 包装脚本使用 `wrapper.lock`；CF22D 使用 `cf22d.lock`；分子图像使用
`render.lock`。这些锁文件位于化学扩展的 `environments` 目录，供安装使用，不决定
研究应选择哪种科学方法。

准备请求时核验所选目标并固定输入、脚本与环境身份，提交和执行时再次检查。缺失绑定、
依赖或已核验回执属于安装缺口，不能据此改用 Host 解释器计算或偷偷更换方法。

保留未满足的要求，并报告具体缺失的绑定。维护者可通过 `scripts/install_job_environment.py`
从随包锁文件安装版本化前缀；研究任务不应修改共享环境。维护后，已有 Job 仍保留原身份。
