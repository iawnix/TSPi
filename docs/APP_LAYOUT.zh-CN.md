# CoRAgent 0.18 安装布局

仅支持全新独立应用布局。旧安装级 `.pi/` 和 `.agents/` 不受支持；请先卸载旧应用并归档数据，再安装。没有旧路径回退、迁移器或兼容链接。

```text
<install>/
  coragent             # 唯一公开客户端入口，经 current 选择版本
  uninstall.sh              # 独立卸载入口
  current -> releases/<id>  # 唯一活动版本指针
  releases/<id>/            # 不可变代码、Skill 文本、脚本和模板
  runtimes/pi/<commit>/     # 启动必需的固定 Pi 运行依赖，不是缓存
  runtimes/maintenance/     # 不依赖活动版本的恢复卸载程序
  etc/installation.json     # 安装身份、Host 环境存储位置、工作区根、服务配置
  etc/job.toml              # 科学执行绑定、Conda prefix、远程队列
  etc/email.toml            # 邮件 Skill 配置
  etc/name-resolver.toml
  etc/pi/                   # Pi 原生模型、认证和设置
  etc/secrets/              # SMTP 等私有密钥
  var/state/installation/   # 安装回执、Python 环境清单
  var/state/host/           # Host 身份、请求回执、持久租约和 Monitor 状态
  var/state/pi/sessions/    # Pi 原生 SQLite 会话
  var/log/                  # 安装和 Worker 日志
  var/cache/                # 可删除并重建的缓存
  workspaces/               # 默认研究数据根，可显式配置其它位置
```

`bin/` 和公开的 `coragentServer` 不再创建。systemd 调用
`current/agent/libexec/coragent-host`，并明确传入安装根目录。日常使用
`./coragent --workspace <name>`，服务管理使用 `systemctl --user … coragent.service`。

Host Conda 基础环境及应用 overlay 存放在
`~/soft/coragent/host-envs/<installation-id>/{base,kernels}/<hash>`；安装器可通过
`CORAGENT_HOST_ENV_ROOT` 指定其它专属路径，该路径会持久记录，运行时不依赖此临时变量。
科学 Job 环境通过 `etc/job.toml` 单独指定；本地与远端解释器分别验证。

Socket 和进程互斥锁位于安装身份隔离的系统 runtime 目录；持久回执不随它清理。
所有者定义以 `research_agent.foundation.layout` 为准，安装器、bootstrap 和诊断工具复用同一实现。
Node 服务由 bootstrap 接收解析后的路径，Skill 从显式配置/环境绑定读取依赖。
工作区内部的 Pi 设置与安装级目录是不同的边界，不按目录名称批量删除。

只读检查：

```bash
python3 scripts/app_layout_doctor.py --install-root /absolute/path --json
```

默认卸载删除所属服务、应用代码和缓存，保留配置、凭据、会话、工作区及 Python 环境。
清理环境需显式选择且校验所属安装，不清除共享科学软件。新安装不自动导入离线归档的旧会话或恢复历史任务。
