# 安装布局重构与全新安装计划

日期：2026-10-07。范围：根据用户要求，先卸载现有应用，再重构源码并全新安装；不实现旧安装兼容、迁移工具或旧路径回退。本文件是实施计划，不代表重构已经完成。

## 1. 已执行的准备与数据边界

- 停止现有 `ts-app-server-tspi.service`，备份安装目录和 systemd unit 后卸载应用。
- 备份记录：`/home/iaw/debug/tspi-test-env/layout-rebuild/backup-location.json`。备份目录仅作为离线数据归档，不在新版路径搜索范围内。
- 保留 `workspaces/`，不取消、重投任何本地或远程科学作业，不发送邮件。停止 Host 不等于取消远端调度作业；重新测试前应只读核对旧作业状态。
- 卸载后将残留的旧安装配置、会话、环境等移出安装根目录归档。新版不接入旧 Host 会话、请求回执、Monitor outbox 或自动接续。
- 不删除 `/home/iaw/soft` 或远端外部软件、科学 Conda 环境。它们可能仍被已提交的作业使用。
- 重构完成前不恢复生产 Host。此时旧工作区的 Monitor 不提供持续监控。

“无需兼容”指源码与新安装不支持旧安装布局，不意味着可以删除研究数据或凭据。旧工作区属于独立数据，不自动修改其内部结构，也不自动重新注册到新 Host。

## 2. 唯一目标布局

```text
/home/iaw/ResearchAgent/
  ResearchAgent                    # 唯一公开客户端入口，不绑定具体 release ID
  uninstall.sh                     # 独立恢复/卸载入口，不依赖运行中的 Host
  current -> releases/<id>         # 唯一活动版本指针
  releases/<id>/                   # 不可变应用发布物
    agent/                         # 应用代码、Skill、脚本、模板、资源摘要
      libexec/                       # Host 和其它内部启动入口
  runtimes/pi/<commit>/            # 固定 Pi 依赖及构建产物，由安装器准备
  etc/
    installation.json             # 安装身份、工作区根、环境存储根、服务设置
    job.toml                       # 本地/远程计算绑定与 submission 配置
    email.toml                     # 邮件设置，密钥使用引用
    name-resolver.toml
    pi/                            # Pi 原生 settings/models/auth 等私有配置
    secrets/                       # 非 Pi 凭据，例如 SMTP 密码文件
  var/
    state/
      installation/                # 安装回执、环境绑定、升级事务记录
      host/                        # Host 身份、输入回执、持久租约、Monitor 状态
      pi/                          # Pi 原生持久会话
    log/                           # 安装、Host、Worker 诊断日志
    cache/                         # Python 字节码、可重建下载缓存等
  workspaces/                      # 默认研究数据根，可在安装配置中另行指定
```

不再创建根目录 `bin/`、`ResearchAgentServer`、安装级 `.pi/`、安装级 `.agents/`、`packages/tspi/` 或第二个 `current`。根目录客户端入口直接解析唯一的 `current`，不需要再绕过 `bin`。这取代此前 APP_LAYOUT 文档中的 `bin` 方案，实施时同步更新中英文规范。

`current` 承担原子选择版本的职责，保留它。安装回执校验指针及其 manifest，不独立选择另一个活动版本。进程启动时解析一次真实 release 路径，使同一进程不因升级混用新旧代码。

Pi 依赖不是可丢弃缓存。安装器按 release manifest 指定的 commit 准备和验证，启动器仅验证并启动。清理 `var/cache` 后应用必须能正常启动。

运行时 Socket、进程互斥锁使用带安装身份的 `$XDG_RUNTIME_DIR` 子目录，系统服务使用对应的 `/run` 管理机制。持久租约、输入回执、幂等记录不能放入易失目录。工作区现有的锁和 `.pi` 是否保留按各自真实用途判定，不进行名称匹配式删除。

## 3. Python 与外部科学环境

```text
/home/iaw/soft/tspi/
  host-envs/<installation-id>/base/<dependency-hash>/
  host-envs/<installation-id>/kernels/<payload-hash>/
  envs/<science-environment-version>/
  locks/
```

- Host 基础 Conda 环境与应用 wheel overlay 保持现有职责隔离；本次不顺带改变依赖组合或科学算法。
- Host 环境路径由安装器生成、验证并记录，release manifest 确定依赖及 payload 身份，运行时不扫描或挑选“最新环境”。
- 科学执行环境只通过 `etc/job.toml` 的环境/backend Python 绑定选择。保留 Conda prefix、lock_ref、软件命令及调度配置合同。
- 本地和远程环境分别准备。远端 prefix 是远端路径，不映射为本地 Host 环境。
- 旧安装的 `.agents` 环境不搬到新 prefix 继续使用；按锁文件在新路径创建，验证解释器、依赖与 wheel 摘要。
- 已有外部科学环境可以作为新 `job.toml` 中明确声明且验证通过的依赖。这是软件绑定，不是旧安装目录兼容。
- 卸载仅清理可证明归属于本安装、且没有运行任务使用的环境；不删除共享 Conda、外部计算软件或科学环境。

## 4. 唯一路径合同与运行时边界

1. 扩展/替换现有 `scripts/app_layout.py` 为唯一的新布局路径定义，删除 legacy/direct/mixed 的运行支持。旧安装只给出清晰的不支持提示，不实现迁移。
2. 布局规则需能在应用依赖尚未安装时使用；Python 启动器、安装/卸载工具复用同源代码，发布时纳入包清单。不能让 bootstrap 依赖尚未创建的 Host Python 环境。
3. Python 解析安装路径后，将必要路径通过受控启动参数或环境传给 Node Host、Worker 和 Monitor；Node 校验这些路径，不再独立拼接 `.pi/...`。
4. 这是文件位置合同，不增加第二套任务状态协议、配置镜像或生命周期数据库。
5. 执行器和 Skill 接收已解析的配置/资源路径。移除 `execution.py` 从工作区及祖先目录搜索 `.pi/job.toml` 的隐式回退。显式指定的配置缺失时直接报错，不退回其它文件。
6. Pi 仍拥有原生认证、模型设置、会话格式；通过受支持的目录参数重定位，不为它维护一份平行配置。
7. Research State 继续拥有 Claim/Node/Attempt、证据和 continuation；Job Runtime 拥有执行回执；Monitor 产生事件；Host 消费并投递。目录重构不改变这些归属。
8. Skill 的文本、脚本、共享资源和摘要随同一 release 发布，使用同一资源索引。不得在 `etc`、缓存或工作区创建另一套活动 Skill 安装。

## 5. 源码修改范围

| 模块 | 必须完成的修改 |
| --- | --- |
| `ResearchAgent`、`ResearchAgentServer`、CLI launcher | 收敛公开命令；Host 移入内部入口；分离客户端/服务端帮助和错误信息；重复 Host 提示实际服务名及管理方式 |
| `scripts/app_layout.py`、bootstrap 路径代码 | 新布局唯一路径定义、安装身份和边界验证；删除旧布局选择与祖先搜索 |
| `install_package.py`、release/package 构建器、包清单 | 新 release store；单个 current；新环境绑定；发布全部 Skill 资源和内部入口；不再生成旧链接 |
| `_runtime_install.py`、`prepare_pi_source.py` | Host Python 放入配置的软件环境根；Pi 必需依赖放入 runtimes；构建失败不能发布可见的半成品 |
| `install_wizard.py`、安装元数据、卸载器 | 使用同一布局和配置；统一高层/底层安装步骤边界；故障回滚、卸载保留和恢复入口 |
| systemd unit 生成器 | 调用内部 Host 入口；正确设置安装身份、配置和环境；只允许必要的 state/log/cache/workspace 写入 |
| Node Host、Pi Worker、Monitor、terminal/link 适配器 | 接收统一路径；会话、回执和日志分开存储；不重新生成旧目录 |
| Job Runtime、email Skill、科学准备脚本 | 统一显式配置路径；email 保持 Skill；不恢复 Provider 或独立生命周期 |
| Phone/Web/Relay 配置与安装代码 | 即使本次只安装 core，也要同步共用路径，避免以后启用组件时重新生成旧目录；独立 Relay 保持独立安装 |
| 文档、公开参考、测试 fixture | 更新使用方式和路径；删除旧布局作为正常安装方式的描述；历史验收记录保留其历史属性 |

当前安装器中嵌套 Agent/Core Package 的内部归档格式不必为目录美观同时重写；先保证唯一外部 release store 和 manifest 权威，不把本次扩展成新的包协议设计。

## 6. 实施顺序

### A. 卸载与归档（本轮）

停止服务、完成私有备份、卸载旧应用、移走残留安装布局，保留工作区。验证没有旧服务或 Host 残留。整理实施计划，不重新安装旧版本。

### B. 定义并贯通新布局

先改路径合同、bootstrap 与安装器，再改 Host/Worker/Monitor/Skill 配置传递、内部服务入口、卸载器和文档。不得出现“新安装器 + 旧运行时默认路径”的中间交付。

### C. 隔离环境验收

所有测试安装、Python 环境、缓存和 fixture 统一置于 `/home/iaw/debug/tspi-test-env/layout-rebuild`；需要短 Unix socket 路径时使用同一测试根下的短目录。测试结束停止并删除测试服务，不污染生产服务或外部软件目录。

### D. 提交并发布可验证的新版本

通过检查后提交、推送，从干净提交构建安装包。应用版本和布局版本明确标记本次不兼容安装变化；构建物记录 commit 和摘要。不得发布依赖未提交路径补丁的安装包。

### E. 全新安装与验收

在 `/home/iaw/ResearchAgent` 按新布局创建新安装身份和新 Host 状态，不恢复旧 session/receipt/Monitor 状态。根据已确认的配置值生成新配置文件，并将仍需使用的凭据放入新私有路径；绝不复制整个旧 `.pi` 或 `.agents`。

默认工作区容器保留；仅在隔离测试安装中新建验收工作区，不扫描旧工作区来重放任务。已有研究数据保持离线可查阅，不为其编写导入兼容器。启动生产 systemd 服务，验证真实安装包和 Worker，记录新布局清单及服务状态。

## 7. 必须通过的验收

- 新安装根不存在安装级 `.pi`、`.agents`、`bin`、公开 `ResearchAgentServer` 或嵌套第二版本指针；不是靠兼容符号链接绕过。
- 安装、客户端、Host、Worker、Monitor、Skill helper 使用一致的配置与 release；更换 cwd、外置 workspace root 后仍一致。
- `ResearchAgent --help` 只描述客户端；内部 Host 帮助准确；重复启动返回服务冲突，不提示更换研究工作区。
- 清空真正的缓存后重启成功；Pi 与 Python 必需运行依赖不位于缓存目录。
- 从全空目录构建、安装和启动成功；启动无需临时下载或修补包源码。
- 真实 pinned Pi fixture：新会话 → Skill 准备文件 → Job → State checkpoint → Host 重启 → 接续恢复 → Monitor 完成事件 → 去重 → 收集 → 用户等待停止。
- 隔离 SMTP fixture 验证 email check/prepare/send/retry，不向真实收件人发送测试邮件。
- 进程重启保留新布局下的会话、输入身份和持久回执；不是通过新建请求绕过恢复失败。
- 新布局内部升级失败可以回滚，活动指针与运行环境一致；这不涉及对旧布局的兼容。
- 卸载后应用入口、所属服务及代码被移除，默认保留配置/凭据、持久状态和工作区；删除用户数据仍需明确选项。
- 所有测试服务被清理，生产安装验收后只保留明确启用的生产服务。

## 8. 明确不做

- 不开发旧安装迁移器、旧路径别名、旧目录搜索回退或两种布局并行支持。
- 不自动导入历史会话，不处理历史 uncertain 回执，不恢复历史 next_run，不重投旧科学作业。
- 不合并 Host 与科学计算 Python 环境，不改变 State/Job/Monitor 生命周期协议。
- 不删除研究工作区、共享软件环境、模型凭据或远端任务来获得“干净安装”。
