# 安装与运维

[English](INSTALLATION.md) | 简体中文

本指南安装 TSPi Agent 及可选的 TS Web 只读投影。TS Phone 是独立的 Flutter
应用；TSPi 不安装 TS Phone server、bridge secret 或本地 HTTP broker。

## 前置条件

- Linux、Git 和 Node.js 22.19+。
- Python 3.11+、Conda/Mamba，以及可写的用户安装目录。
- `config/pi-source.json` 指定版本的 Pi 源码 checkout；安装器也可以自动下载并修补。
- 可选的 systemd user service 和 TS Web 端口。创建受管科学运行时需要 Conda/Mamba。

## 安装或选择版本

运行 `./install.sh`，确认安装目录、TSPi revision、workspace root、Conda root、
可选 TS Web 组件和服务策略。Core Agent、科学运行时和分子渲染工具始终安装。
非交互安装可使用 `--workspace-root /absolute/path`；默认值为
`<install>/workspaces`。Host、终端、TS Web 和卸载器共享
`.pi/tspi/workspace-root.json` 中记录的值。

发布通过以下选择器原子切换：

```text
<install>/.pi/packages/tspi/current -> releases/<release-id>
```

只有选中的 release 会暴露给 `TSPi` 启动器；安装器记录校验和，不执行该 release
之外的源码。

可选模型图标字体可通过 `--with-model-icons` 安装，使用
`--without-model-icons` 禁用。字体属于用户数据目录，不是科学运行时依赖；
`TSPI_ICON_STYLE=unicode` 或 `nerd` 可显式覆盖选择。

## 受管 Python 运行时

运行时位于 `<install>/.agents/envs/tspi`，元数据位于
`<install>/.agents/runtime/tspi`；缓存位于 `<install>/.pi/runtime-cache`，可删除后
重建而不会影响工作区。运行时探针会检查反应解析、ASE 热模型、几何和渲染。
固定版本的 Pi 源码还需要模型数据和 workspace build 产物，缺失时运行：

```bash
scripts/prepare_pi_source.py --install <root>
```

## 配置远程执行

本地计算在持久化 Attempt 子进程中执行；远程执行临时镜像输入并将结果收回本地。
两者共享 `ts_calc` 的 `prepare -> submit -> inspect -> collect -> parse` 生命周期，
只有 remote profile 包含 SSH/Torque 字段。推荐配置文件为
`<install>/.pi/compute.toml`，模板位于 `config/compute.example.toml`：

```bash
./TSPi --check-remote
```

当前远程合同只支持 Torque/PBS。配置必须声明 SSH、可写远程根目录、允许队列及站点
管理的 Gaussian/xTB/CREST/ASE-NEB 命令；TSPi 不安装远程软件。配置文件应保持
`0600`，凭据留在 SSH 配置中。

本地后端可通过 `--local-config /absolute/path/local.toml` 选择已有的 Gaussian、
xTB、CREST 和 ASE-NEB 可执行文件。TSPi 不会下载 Gaussian，也不会静默安装任意
本地化学程序。

## 安装日志、通知与 Host

安装日志位于安装目录的 `.pi/tspi/logs/`。通知配置只保存投递所需的非秘密元数据，
SMTP 或其他凭据由受管环境提供。

使用 systemd 启动唯一的安装级 Host：

```bash
systemctl --user enable --now ts-app-server-tspi.service
```

一个 Host 可以服务 workspace root 下的多个直接子工作区。终端和 TS Phone 连接同一
session Worker，不创建第二个 Agent runtime。

## 工作区初始化与 TS Web

首次运行 `./TSPi --workspace <name>` 时，客户端会在配置的 workspace root 下创建并
校验命名工作区。TS Web 是可选的只读浏览器投影；它读取版本化 projection，不拥有
规范科学状态，也不提供科学写入路由。

## 模型配置

模型目录、认证存储、API adapter 和 `models.json` 由固定 Pi release 提供。终端、TS
Phone 和其他客户端连接同一 session，因此共享模型和工具集合；模型兼容性见
[Model Compatibility](MODEL_COMPATIBILITY.md)。

## 升级、回滚和恢复

升级先构建并校验新的 content-addressed release，再原子更新 `current`，最后重启
Host。回滚时停止 Host，选择 `.pi/packages/tspi/releases` 下的上一份已验证 release，
然后重新启动；不要删除 workspace JSON 或科学记录。若计算正在运行，先检查 Attempt
状态，再重启服务；有 user systemd 时本地计算由独立临时 service 托管。

卸载器只删除安装目录及其受管运行时，不删除用户显式指定的 workspace root，除非
用户单独确认。
