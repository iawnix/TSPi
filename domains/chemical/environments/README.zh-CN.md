# 化学执行环境

[English](README.md)

这些资源供安装使用，与 Host 控制环境分离。Conda 显式锁为每个包固定 SHA-256，
目标为 Linux x86_64。`wrapper.lock` 要求 glibc >=2.17，科学与渲染锁要求
glibc >=2.28。CF22D 选择通用 x86_64 PySCF 构建，不绑定维护者的 CPU。
其他目标需要单独核验适合该目标的锁文件。

| 锁文件 | 绑定 | 内容 |
| --- | --- | --- |
| wrapper.lock | Gaussian/xTB 包装脚本 | Python 3.11 与安装工具；原生求解器单独安装 |
| structure.lock | structure、validation | RDKit 与 NumPy |
| cf22d.lock | pyscf | PySCF、geomeTRIC 和 dispersion，全部由 Conda 安装 |
| render.lock + render.requirements.txt | render | RDKit、Cairo、Matplotlib、xyzrender 及其依赖 |

文本报告只使用 Host 标准库，不需要渲染锁。渲染环境中的 notebook 依赖来自
xyzrender 上游要求，只安装在渲染目标中。这些环境均不安装 CoRAgent wheel。

统一入口 `install.sh` 根据 `manifest.json` 准备环境。首次安装没有提供 `job.toml`
时，默认选择本地 `structure`；已有绑定保留。其他环境显式选择：

```bash
./install.sh --source local --job-profile local:pyscf --job-profile local:render
./install.sh --job-config /absolute/job.toml --job-profile cluster:pyscf \
  --job-software-root cluster=/absolute/managed-science \
  --job-conda cluster=/absolute/conda/bin/conda
```

先在 `job.toml` 配置远端、队列与原生求解器路径。远端路径属于目标机器。准备阶段
通过 SSH 执行，目标需要 Python 3.11+、Conda、`timeout`、Linux x86_64 及声明的
glibc；执行阶段使用已配置的 PBS/Torque 和 rsync。本机 Python 路径不会复制给远端。
`wrapper` 只为已配置的 Gaussian/xTB 后端准备 Python，原生程序仍由管理员提供。

安装器把固定锁和不可变的版本化环境保存在专用受管目录，本机默认是
`~/soft/coragent/job-envs/<installation-id>`，再将绝对路径写入 `etc/job.toml`。
PubChem/OPSIN 服务参数位于 `etc/name-resolver.toml`。本地完成名称解析和结构准备后，
可以交给远端计算，不要求每个计算目标都安装名称解析服务。

切换当前版本或停止服务前，先完成准备与有时限的实际验收 Job。structure 检查
RDKit、Job 内的解析器配置路径和乙醇结构生成；其他环境执行声明的最小计算或渲染。
报告区分环境验证、已测试后端和未验证目标。离线验收不访问外部名称服务。已有远端
仅在选择准备该目标或显式传入 `--verify-job-target cluster` 时验证。

管理员维护时仍可使用底层目标端工具：
`python3 scripts/install_job_environment.py --config /absolute/job.toml --environment local --backend structure`。
它要求已有显式绑定，不负责统一安装器的版本切换或 Job 验收。结构与验证可以共用
前缀；CF22D 不需要自定义激活脚本或 `LD_PRELOAD` 补丁。

安装时不重新求解依赖。固定的 pip 产物下载到环境父目录下的缓存，再以
`--require-hashes`、`--no-deps` 安装，并用 `pip check` 检查依赖完整性。
主入口的 `--job-offline` 仅使用预先准备的缓存。底层工具的 `--package-cache`
可指定产物目录；`--offline` 仅使用该目录与 Conda 缓存
（`CONDA_PKGS_DIRS`）。锁与发行文件保持只读。新建安装中断后删除该次创建的前缀，
已有前缀不就地更新。显式 `--adopt` 才会核验预先准备的环境并发布安装回执。

绑定配置完成后，用已安装的控制解释器执行
`-m research_agent.application.environment_check --config /absolute/job.toml`，核验实际目标与声明的
依赖导入，包括 SSH 目标。随后运行有时限的科学 Job；包清单和导入一致不代表方法
已经有效工作。

更新锁时，在隔离环境中以 `CONDA_OVERRIDE_ARCHSPEC=x86_64` 从 conda-forge 求解
记录的根依赖，使用 `conda list --explicit --sha256` 导出，并在全新安装及实际计算
通过后发布。pip 条目必须附上游产物的摘要。不要导出凭据、引入仅本机存在的 wheel，
或就地替换正在使用的安装锁。
