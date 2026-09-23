# CF22D 环境 Doctor

Doctor 是只读就绪探针。它不得提交计算、修改 ResearchMap 状态、向安装级 runtime 安装
软件，或清理 Runner 自己 scratch 子目录之外的文件。

## 内容

- [运行时机](#运行时机)
- [检查项](#检查项)
- [就绪与恢复](#就绪与恢复)
- [能力边界](#能力边界)

## 运行时机

首次 CF22D 计算前、修改所选本地/远端环境或 `compute.toml` 后，以及修改受管 Python
release 或原生库后，都应运行 doctor。之前的成功结果不能证明另一个环境或 capability
已经就绪。

远端目标使用安装级只读环境诊断（`TSPi --check-remote`）。使用 `ts_environment` 查看已
配置的环境及其 Backend 绑定；不要用临时 SSH 命令替代。现有远端合同会检查连接、调度器、
可写远端根目录、队列/节点、激活脚本和每个已注册 Backend；计算 preflight 仍会再次检查
远端就绪状态。`TSPi --check-remote` 仅面向远端。本地目标应使用安装级或 adapter 暴露的
runtime probe；若没有 probe，就把计算 preflight 当作就绪门槛，不要声称存在独立的本地
doctor。

## 检查项

PySCF/CF22D adapter 的 doctor 应逐项报告检查结果，并在可用时记录版本和来源：

1. 所选 interpreter 以及 `pyscf-runner` entry point 或 module 来自安装级 runtime；
2. `import pyscf`、`geometric`、`numpy`、`yaml`（PyYAML）、`psutil` 和 PySCF dispersion
   module 成功，并记录 module 来源；不能接受意外的 user-site 导入；
3. PySCF 能在微型探针分子上，以 `xc="CF22D"` 和配置的基组/电荷/自旋构造 DFT 对象。
   这是有边界的探针，不能当作科学结果；
4. 配置的网格等级、SCF 容差和循环上限能被接受；探针不必执行生产级优化或频率；
5. 所选 scratch 基目录可写，能创建并删除唯一子目录，且不触碰基目录或其他运行；
6. 请求的线程数、PySCF 内存预算和调度器资源上限可以表达。adapter 的 `memory_mb`（源
   名称为 `max_memory_mb`）是 PySCF 预算而不是 OS 硬限制，应为调度器和解释器留余量；
7. 输出与 checkpoint 目标可写，且不会在没有显式 intent 的情况下覆盖现有 Artifact。

若 adapter 支持远端执行，应在配置的激活环境和 Python 中执行同样的依赖/探针检查。命令
出现在 `PATH` 中并不足够；module 来源和 CF22D 构造必须属于所选环境。

## 就绪与恢复

返回包含 `ok`、环境身份、解释器与 module 版本/来源、scratch/输出检查及有边界错误消息的
结构化结果。缺包、CF22D 构造失败、路径不可写或超出资源上限都属于 `not_ready`，不是科学
计算失败。

修复安装级 runtime 或环境配置后重新运行 doctor。不要在研究任务内向共享 hash-addressed
runtime 执行 pip 安装，不要修改 `compute.toml` 来绕过限制，也不要重试已经改变 intent 的
计算。报告为何阻止执行时，应把 doctor 记录与计算计划一并保留。

## 能力边界

Doctor 只证明 runtime 就绪，不注册 capability、不选择方法、不验证过渡态，也不建立反应
机理。`ts_state mode=capabilities capabilityKind=compute` 中出现 descriptor 同样不能证明
所选本地/远端环境健康。

当 TSPi adapter 尚未发布准确的输入/输出 role、解析和任务验证合同时，doctor 只能用于
诊断。不要为源任务 `sp`、`opt`、`ts`、`freq` 或 `thermo` 虚构公共 ID；只使用实时 catalog
返回的版本化名称。即使这些单结构 capability 已注册，源 Runner 仍没有公开的 IRC、NEB、
交叉点、端点或多结构 capability。
