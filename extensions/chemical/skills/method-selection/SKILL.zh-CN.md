---
name: method-selection
description: 选择科学方法并准备命名计算环境；用户已经指定方法时同样用于执行准备。
---

# TSPi 方法选择

[English version](SKILL.md)

选择方法或准备已指定方法的执行时使用本 Skill。辅助脚本生成通用 Job 请求，由 Agent 提交执行。

从区分相关 Claim 所需的 Finding 出发，考虑体系大小、电荷、自旋、电子态、金属或多参考
风险、溶剂、约束、目标可观测量、预期误差、候选质量与成本。使用 `job_probe` 检查所选
环境，不要只根据 Skill 描述推断软件可用。选择命名的本地或远端环境，由 Skill 构造准确
命令和参数。

只有低成本探索能回答已声明问题时才使用它。明确何时需要更高层级计算、替代方法或稳健性
检查，并把选择与理由保存在 Node 和不可变 calculation intent 中。

对于明确要求优化/单点并比较多个方法和执行环境的请求，先展开完整的
`方法 × environment × {opt, sp}` 矩阵，再逐项探测环境并分别记录单元失败。当前第一方
方法路由遵循以下规则：

| 方法 | 程序 | Job 命令 |
| --- | --- | --- |
| CF22D | PySCF | cf22d/scripts/run.py |
| GFN2-xTB | xTB | `xtb` 优化 / 单点 |
| HF、M062X 及其他 Gaussian Route Section 方法 | Gaussian | 带 `.gjf` Route Section 的 `g16` |

Gaussian 方法和基组写入 `.gjf` 的 Route Section，例如
`# M062X/6-31G** Opt` 或 `# HF/6-31G** SP`。在上述比较中，每个 `sp` 依赖同一方法、同一环境的 `opt` 输出。
其它研究可选择明确的固定几何或 TS/Freq/IRC/scan 输入，由 Agent 定义计算依赖。
某个矩阵单元不可用时只阻塞该单元，不能静默替换方法或停止其他独立单元。

## 参考资料

- [method_selection.zh-CN.md](references/method_selection.zh-CN.md)：科学判据。
- [backend_contract.zh-CN.md](references/backend_contract.zh-CN.md)：科学 Job 合同与执行边界。
- [job_probes.zh-CN.md](references/job_probes.zh-CN.md)：命名的本地/远端环境及远端
  Platform 细节。
- [runtime_environment.zh-CN.md](references/runtime_environment.zh-CN.md)：安装级科学运行时诊断。

## 可执行请求准备

使用 [scripts/prepare_job.py](scripts/prepare_job.py) 从 job.toml 生成通用 Job 请求。传入 --config "$TS_JOB_CONFIG"、--environment、--backend、--skill、--xyz，-- 后是 runner 参数。用安装版 TSPI_PYTHON 执行 helper；解释器来自 job.toml 的 Conda 绑定。核对参数，补充 nodeId/timeoutSeconds 后 job_start。辅助脚本会暂存完整 scripts 目录和 `_shared` 依赖。

保留准备请求中的 requestId；同一次提交恢复时复用它，不因工具响应丢失而生成新 ID。明确重算时生成新请求。

执行显式 Gaussian 输入时，用 `--input-gjf <file>` 替代 `--xyz`。
通过 `--dependency /absolute/source.chk=previous.chk` 暂存检查点或包含文件，
目标名称须匹配 `.gjf` 内的相对引用。用 `--collect ts.chk` 要求收集可供后续复用的检查点。
这些参数放在 `--` 前；`--validation saddle` 或 `--validation irc` 等 runner 参数
放在其后，不传 `--task`。输入格式、依赖文件内容、收集要求及脚本资源均参与请求身份计算。
helper 只封装当前计算，计算顺序由 Agent 决定，数值检查须结合 Gaussian Skill 作科学解释。

选择方法或准备已指定方法的执行时都使用本 Skill。从列出的路径读取具体方法 Skill。读取安装配置、检查方法可用性属于 Agent 的工作，尚未验证不应自动变成用户输入门槛。

Python 依赖由安装阶段创建的 Conda 环境隔离，并通过 job.toml 的结构化 python 绑定选择：backend.python 优先，否则继承 environment.python。用 "$TSPI_PYTHON" 执行本地准备 helper；远程 runner 使用配置的 Conda prefix，不猜 python3、不用 --python 覆盖。CF22D 使用 backends.pyscf.python，不再同时指定 Python command。缺失环境交由安装维护处理，不在研究回合临时 pip install。


在 `--` 前传 `--output <workspace>/prepared/<cell>.json` 保存完整请求。脚本输出
requestFile/requestSha256，直接交给 job_start，只补 nodeId 和可选 timeoutSeconds；
不要手抄 command/inputs。相同输入与配置保留 workId/requestId，主动重新计算才用
--work-id 指定新身份。修改请求文件后必须重新核对并计算摘要。

远程 job.toml 的 environment 或 backend 必须明确配置 submission.queue；
submission.resources 保存 CPU、内存、walltime，backend 覆盖环境默认值。
allowed_queues 不负责选择队列。缺配置交由安装维护，不猜队列。可用
submission.queue_wait_seconds 设置一次性排队超时诊断事件；收到后查看
job_status.diagnostics。Q/R 尚无退出回执是正常现象；重投或改队列前先对账原 Job。
