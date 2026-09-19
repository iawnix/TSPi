# 运行环境合同

TSPi 使用由安装管理、供多个 workspace 共享的 Python runtime：科学依赖位于按摘要寻址的
Conda 环境，所选 Kernel wheel 位于 venv。

`scripts/install_env.py` 绑定包根目录、环境 spec 摘要、解释器、必需渲染依赖、runtime
manifest 与环境前缀。正式 release 包含一个受 manifest 绑定的 `ts-agent-kernel` wheel；
安装器重新校验并安装该 wheel，不在只读 release 中构建。作者 checkout 则在临时副本中
构建 wheel。两条路径都会记录所有已安装模块与包数据的摘要。

RDKit、兼容范围的 NumPy、Matplotlib 和 `xyzrender` 是核心依赖。写入 runtime manifest
前，安装器会验证 NumPy/RDKit/Matplotlib 导入、SMILES 解析、固定种子的 ETKDG 嵌入、
UFF 优化和 `xyzrender` 可执行程序，并记录版本与来源。只有源码和已安装 distribution
摘要仍匹配时，`packages/ts-agent-kernel/ts_agent/runtime/launcher.py` 才接受 manifest。

研究 workspace 保存状态与 Artifact；安装 runtime store 保存 Python 环境；release 目录
保存有版本的程序文件。

TSPi 将 manifest 选择的解释器导出为 `TS_AGENT_PYTHON`，把其 `bin` 前置到 `PATH`，
禁用用户 site package，并为 Pi 进程树清除 `PYTHONHOME`。缺失或无效 runtime 通过安装器
修复。

诊断失败时，分别检查 release、Python payload 摘要、manifest、spec 摘要、解释器、probe
模块来源和 renderer。重新把所选 release 安装到按摘要寻址的环境，不要就地修改。
