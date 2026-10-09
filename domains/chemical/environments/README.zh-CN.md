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
xyzrender 上游要求，只安装在渲染目标中。这些环境均不安装 ResearchAgent wheel。

将所需锁复制到目标的持久目录，保持 `render.requirements.txt` 与 `render.lock`
相邻。在安装管理的 `job.toml` 中配置目标绝对路径：`conda_executable`、新的版本化
`prefix` 和 `lock_ref`。`config/job.example.toml` 中的 `/opt` 路径是可编辑的
示例；本机软件可放在维护者的 `~/soft` 下。

在目标主机运行安装器，SSH 目标也一样：

```bash
python3 scripts/install_job_environment.py --config /absolute/job.toml --environment local --backend structure
python3 scripts/install_job_environment.py --config /absolute/job.toml --environment local --backend pyscf
python3 scripts/install_job_environment.py --config /absolute/job.toml --environment local --backend render
```

选择 Gaussian 或 xTB 的后端名安装共用的 wrapper 前缀。结构与验证可以引用同一个
前缀和锁。CF22D 不再需要自定义激活脚本或 `LD_PRELOAD` 补丁。

安装时不重新求解依赖。固定的 pip 产物下载到环境父目录下的缓存，再以
`--require-hashes`、`--no-deps` 安装，并用 `pip check` 检查依赖完整性。
`--package-cache` 可指定产物目录；`--offline` 仅使用该目录与 Conda 缓存
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
