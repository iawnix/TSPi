# 执行环境选择

`CORAGENT_PYTHON` 是安装管理的控制解释器，用于准备请求和整理已有证据，不提供科学库。

根据方法 Skill 选择预设入口、原生命令或任务脚本，以及 `job.toml` 中的命名环境。
所选绑定提供目标 Python 或原生程序；预设入口还声明自己的依赖。
结构准备与化学验证器可共用 `structure.lock` 环境；Gaussian/xTB
的 Python 包装脚本使用 `wrapper.lock`；CF22D 使用 `cf22d.lock`；分子图像使用
`render.lock`。这些锁文件位于化学扩展的 `environments` 目录，供安装使用，不决定
研究应选择哪种科学方法。

准备请求时已经核验所选目标。准备前需要诊断时，只检查选定的入口和环境：

```bash
"$CORAGENT_PYTHON" -m research_agent.application.environment_check --config "$CORAGENT_JOB_CONFIG" --environment <环境> --executor <id> --version <版本>
```

使用没有预设入口的原生命令或任务脚本时，将 executor/version 换成 `--backend <绑定>`。
默认核验绑定中配置的 Python 与原生程序；用 `--runtime native` 或 `--runtime python`
选择具体运行方式。只连接所选环境，远端也一样。需要底层观测详情时加 `--details`。

`verified` 表示所选前置条件通过，计算结果由实际科学 Job 提供。
`not_configured` 标识缺失的环境或后端；`check_failed` 给出具体绑定、依赖或探测错误。
`recipe_not_found` 仅表示该 id/version 没有预设入口，应回到方法 Skill 检查其后端、
原生命令或任务脚本。不能用预设入口索引判断软件是否可用。

准备请求时核验所选目标并固定输入、脚本与环境身份，提交和执行时再次检查。缺失绑定、
依赖或已核验回执属于安装缺口，不能据此改用 Host 解释器计算或偷偷更换方法。

保留未满足的要求，并报告具体缺失的绑定。维护者可通过 `scripts/install_job_environment.py`
从随包锁文件安装版本化前缀；研究任务不应修改共享环境。维护后，已有 Job 仍保留原身份。

原生程序的前置探测只解析并固定所配置可执行文件的摘要，不运行求解器，也不证明许可、
收敛或科学结论成立。`environment_executable_missing` 表示所选命令无法执行；
`environment_activation_missing` 表示激活脚本缺失；`environment_dependency_missing`
表示要求的包或模块缺失；`environment_import_failed` 表示已有依赖导入初始化失败。
报告实际观测与所选目标：未配置绑定或没有预设入口不等于所有环境都未安装软件。
绑定或程序字节发生变化后须重新准备请求，不能继续派发旧准备命令。
