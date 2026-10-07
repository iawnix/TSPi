---
name: gaussian
description: 准备、运行并检查 Gaussian 单点、优化、频率、扫描、过渡态、IRC 与 QST 计算。
---

# Gaussian 计算

使用随 Skill 安装的 [scripts/run.py](scripts/run.py) 生成输入、执行程序并验证结果。先读取安装级 `job.toml` 中目标环境的 `gaussian` command、activation_script 和 environment；本地 `/home/iaw/soft` 与远程安装路径分别解析。

通过 [准备脚本](../method-selection/scripts/prepare_job.py) 生成通用 `job_start` 请求：

```text
"$TSPI_PYTHON" <method-selection>/scripts/prepare_job.py --config <job.toml> --environment <环境名> --backend gaussian --skill gaussian --xyz <结构.xyz> -- --task opt-sp
```

确认方法、基组、电荷、自旋和资源，补充 nodeId 与 timeoutSeconds 后提交返回的请求。脚本不会替 Agent 提交任务。它会暂存该 Skill 的 scripts 和 `_shared` 依赖，保留相对目录；不要只复制 run.py。激活发生在目标 Job 中，不需要 Provider 注册。

`run.py --help` 给出准确参数；`--task opt-sp` 明确执行优化，再以优化结构执行单点，任何步骤失败都会非零退出。`--spin` 是 2S（Gaussian 多重度为 spin+1）；XYZ 单位为 angstrom。选择新的空输出目录，不覆盖之前尝试。

声明 `results/result.json` 和 `results/geometry.xyz` 为 required 输出，并收集步骤目录的原始日志。结果记录实际方法、基组、输入与几何摘要、能量单位、收敛证据和脚本摘要。Job 退出 0 之外，还要检查 `validated=true` 及所需 steps；确认 opt 与 SP 的结构绑定。失败保留 result.json 和已有日志，不能用最后一个能量字符串替代完整验证。

通过 `job_status/job_collect/job_reconcile` 跟踪任务；使用返回的真实 attempt_id 保存等待点。科学 Finding 由 Agent 根据证据登记。Runtime 不判断化学方法，不允许静默换方法、基组或系统解释器。

默认方法 M062X、基组 6-31G**。输入采用 Opt=Tight 或 SP、SCF=Tight、Int=UltraFine；每步独立日志，检查方法/基组回显、正常终止和优化收敛。没有频率证据不能声称极小值已验证。TS、频率、IRC 与端点计算的顺序由 Agent 通过下面的显式输入接口自行组织。

详细检查见 [gaussian_validation.zh-CN](references/gaussian_validation.zh-CN.md)。

Python 依赖由安装阶段创建的 Conda 环境隔离，并通过 job.toml 的结构化 python 绑定选择：backend.python 优先，否则继承 environment.python。用 "$TSPI_PYTHON" 执行本地准备 helper；远程 runner 使用配置的 Conda prefix，不猜 python3、不用 --python 覆盖。CF22D 使用 backends.pyscf.python，不再同时指定 Python command。缺失环境交由安装维护处理，不在研究回合临时 pip install。

## 显式 Gaussian 输入

TS/Freq/IRC/QST/扫描任务在工作区准备完整 .gjf。method-selection helper 用
--input-gjf 替代 --xyz；-- 后传 --method、--basis、--charge、--spin、
--threads、--memory-mb 与 --validation。每个 Link1 必须显式声明要求的方法/基组、
%nprocshared 和 %mem；电荷/多重度必须一致。Geom=AllCheck 继承 checkpoint
信息，Agent 需另行核对来源。-- 前用 --dependency /绝对路径/source.chk=previous.chk
暂存依赖；文件引用必须是相对路径。--collect ts.chk 收集 results/ts.chk 供后续 Job 使用。

```text
"$TSPI_PYTHON" <method-selection>/scripts/prepare_job.py --config "$TS_JOB_CONFIG" --environment local --backend gaussian --skill gaussian --input-gjf ts.gjf --collect ts.chk --output prepared/ts.json -- --method M062X --basis '6-31G**' --charge 0 --spin 0 --threads 12 --memory-mb 4000 --validation saddle
```

--validation 可选 opt/sp/frequency/minimum/saddle/irc/none。
saddle 检查驻点收敛及一个虚频；模式方向仍由 Agent 检查。IRC 输出路径点及端点证据，
路径完整性与盆地归属需要解释。显式输入结果分别记录 execution_succeeded、
normal_termination、checks_passed、scientific_validation，保持 validated=false。
科学判断记录到 Research State，不要改写 result.json 提升验证状态。
正常终止不能证明极小值、TS 或机理。保留原始日志/checkpoint；分支、重试和停止由
research_strategy 表达，helper 只运行所给输入，不替 Agent 选择下一项实验。
