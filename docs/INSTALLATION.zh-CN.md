# 安装与运维

[English](INSTALLATION.md) | 简体中文

本指南安装 TSPi Agent 及可选的 TS Web 只读浏览器。TS Phone 是独立的 Flutter
应用。TSPi 本地安装只包含 Host 侧 Link 客户端；公网 TSPi Link Relay 使用独立安装器。

## 前置条件

- Linux、Git 和 Node.js 22.19+。
- Python 3.11+、Conda/Mamba，以及可写的用户安装目录。
- `config/pi-source.json` 指定版本的 Pi 源码 checkout；安装器也可以自动下载并修补。
- 可选的 systemd user 或 system service 和 TS Web 端口。创建受管科学运行时需要 Conda/Mamba。

启动脚本默认使用公开 HTTPS 仓库；Git 传输中断时会有限重试，仍失败则回退到普通
浅克隆。私有 GitHub 仓库可显式传入 SSH 地址：

```bash
./install.sh --tspi-repo git@github.com:your-org/TSPi.git
```

## 安装或选择版本

运行 `./install.sh`，确认安装目录、TSPi revision、workspace root、Conda root、
可选 TS Web 组件和服务策略。Core Agent、科学运行时和分子渲染工具始终安装。
非交互安装可使用 `--workspace-root /absolute/path`；默认值为
`<install>/workspaces`。Host、终端、TS Web 和卸载器共享
`.pi/tspi/workspace-root.json` 中记录的值。

交互安装器中的 `Review and install` 会显示完整安装计划。按 Enter 或输入 `Y` 开始安装；
输入 `N` 会返回配置菜单继续修改，尚未写入安装文件或启动服务。选择 `9) Quit` 才会退出
安装器并保持未安装状态。

发布通过以下选择器原子切换：

```text
<install>/.pi/packages/tspi/current -> releases/<release-id>
```

只有选中的 release 会暴露给 `TSPi` 启动器；安装器记录校验和，不执行该 release
之外的源码。

可选模型图标字体可通过 `--with-model-icons` 安装，使用
`--without-model-icons` 禁用。字体属于用户数据目录，不是科学运行时依赖；
`TSPI_ICON_STYLE=unicode` 或 `nerd` 可显式覆盖选择。模型字形使用补充私用区，避免被
终端主 Nerd Font 中已有的同码位字形遮蔽。

## 受管 Python 运行时

运行时位于 `<install>/.agents/envs/tspi`，元数据位于
`<install>/.agents/runtime/tspi`；缓存位于 `<install>/.pi/runtime-cache`，可删除后
重建而不会影响工作区。运行时探针会检查反应解析、ASE 热模型、几何和渲染。
固定版本的 Pi 源码还需要模型数据和 workspace build 产物，缺失时运行：

```bash
scripts/prepare_pi_source.py --install <root>
```

## 配置计算后端

本地计算在持久化 Attempt 子进程中执行；远程执行临时镜像输入并将结果收回本地。
两者共享 `ts_calc` 的 `launch`、`inspect`、`finalize`、`cancel` 公开操作；这些操作
分别封装 prepare/submit、status/可选 tail、collect/parse 和 cancel 内部动作。
只有 remote 环境包含 SSH/Torque 字段。安装器统一接收一份计算后端 TOML 文件：
交互安装时在提示处输入文件路径，非交互安装时使用
`--compute-config /absolute/path/compute.toml`。项目模板位于
`config/compute.example.toml`；复制后按目标机器修改 local/remote environment 及其 backend
绑定，再交给安装器。
安装后的文件为 `<install>/.pi/compute.toml`，权限为 `0600`。

`/compute` 和 `compute.environments` 会列出已配置的本地与远端环境，
TSPi 不会下载 Gaussian 或其他站点管理的本地化学软件，SSH 凭据仍由 SSH
配置管理，不会复制到该 TOML 文件中。

当前远程合同只支持 Torque/PBS。配置必须声明 SSH、可写远程根目录、允许队列及站点
管理的 Gaussian/xTB/CREST/ASE-NEB 命令；配置文件应保持 `0600`。执行层会在准备远端
计算时完成必要的就绪性检查；交互查看配置使用 `/compute`。

## 安装日志、通知与 Host

安装日志位于安装目录的 `.pi/logs/`。通知配置只保存投递所需的非秘密元数据，
SMTP 或其他凭据由受管环境提供。

安装器可以启用并启动唯一的安装级 TSPi Host。Host 是 control plane；每个活动 session
由安装级 Pi App Server 中一个固定版本的 `SessionWorker`/`AgentHarness` lane 拥有。日常
使用直接打开 workspace；配置的 service 未运行时，TSPi 会自动启动并等待它就绪：

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a -c
```

一个 Host 可以服务 workspace root 下的多个直接子工作区。终端、TS Phone 和 Monitor
通过 Host 连接同一个 Harness lane，不创建第二个 Agent runtime。默认终端使用 Pi 官方
native client 连接 Host 返回的本地 descriptor，不需要 tmux 或 PTY scraping；客户端关闭
不会停止 worker 或当前 turn。`TSPI_HOST_BACKEND=ordinary` 仅用于迁移/调试。

规范 format-4 transcript 位于 `.pi/app-server-host/sessions/<encoded-cwd>/`，请求回执、scheduler
lease、Monitor outbox 也位于安装级 Host state。systemd 重启后这些 durable operation/queue
ID 仍可恢复，客户端通过新的 Host epoch/cursor 重新附着。

## Monitor 运维

Host 为 workspace root 启动一个 Monitor worker，轮询持久化 Compute 状态，并在每个
workspace 内写入 registration、event 和 delivery 回执。`monitor/list`、`monitor/status`、
`monitor/enable`、`monitor/disable` 提供健康状态和积压信息。wake 与 notification 分别
确认、租约和退避；wake 只表示 Pi 接受了输入，不表示 agent turn 已完成。Root Agent
必须重新读取 `ts_state`、检查计算后才能修改 ResearchMap。

`workspace.json` 中稳定的 `ws_<hex>` 身份会先被验证，再映射到 Host 使用的直接目录名，
防止 foreign event 投递到错误项目。

## 旧历史迁移

workspace `.pi/sessions/*.jsonl` 的 v3 历史保持只读。使用
`apps/app-server/tspi-history.mjs` 盘点；只有显式指定 `--source` 并加 `--import` 才会在
安装级 session root 生成新的 format-4 文件。源文件按 hash 校验并保持不变，
`.pi/app-server-host/history-imports/` 写入 provenance 报告。活动操作、残缺文件、不支持的
记录或 workspace 归属有歧义时会拒绝，不会重放。

## TS Phone 与 TSPi Link

安装时启用 Phone access，并填写 TSPi Link Relay 的 HTTPS 地址以及 Relay 管理员生成的
一次性 Host enrollment code。安装器会写入 `.pi/app-server-host/link.json` 和仅安装
用户可读的 `.pi/app-server-host/host.token`。Host 只向 Relay 建立出站 WSS，不需要把
App Server 端口暴露到公网。

Host 上线后，使用下面的命令管理手机授权：

```bash
./TSPi phone pair
./TSPi phone devices
./TSPi phone revoke <device-id>
```

`phone pair` 输出 TSPi Link Relay URL 和 8 位配对码。配对码有效期五分钟且只能使用一次；手机
兑换得到的可撤销设备凭据保存在平台安全存储中。Link 凭据与 TS Web HTTP token 相互独立。

## 工作区初始化与 TS Web

首次运行 `./TSPi --workspace <name>` 时，客户端会在配置的 workspace root 下创建并
校验命名工作区。TS Web 是可选的只读浏览器；它直接读取 canonical ResearchMap，
不拥有第二份科学状态，也不提供科学写入路由。

## 模型配置

模型目录和 API adapter 由固定 Pi release 提供。安装时，安装器会把 Host 服务账户
`~/.pi/agent/` 中已有且安装目录缺失的 `models.json` 与 `auth.json` 复制到私有安装状态
`<install>/.pi/agent/`；升级不会覆盖安装目录中已有的文件。如果没有可导入的配置，必须先
通过 Pi 或 provider 环境变量配置凭据，再创建 TSPi 会话。终端、TS Phone 和其他客户端连接
同一 session，因此共享模型和工具集合；模型兼容性见
[Model Compatibility](MODEL_COMPATIBILITY.md)。

## 升级、回滚和恢复

升级先构建并校验新的 content-addressed release，再原子更新 `current`，最后重启
Host。回滚时停止 Host，选择 `.pi/packages/tspi/releases` 下的上一份已验证 release，
然后重新启动；不要删除 workspace JSON 或科学记录。若计算正在运行，先检查 Attempt
状态，再重启服务；有 user systemd 时本地计算由独立临时 service 托管。

卸载器只删除安装目录及其受管运行时，不删除用户显式指定的 workspace root，除非
用户单独确认。
