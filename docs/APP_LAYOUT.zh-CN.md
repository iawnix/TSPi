# Research Agent 独立 APP 布局

Research Agent 是独立应用，Pi 只是私有 Runtime Adapter。目标布局为：

```text
<install>/
  bin/                  # 稳定入口 shim
  releases/<id>/       # 不可变 application release
  current -> releases/<id>
  etc/                  # 配置和 owner-only 密钥
  var/                  # workspace、session、artifact、日志和锁
```

当前安装器仍支持历史 `<install>/.pi/packages/tspi` 布局，但它只能作为迁移
来源，不能与新布局形成第二套状态权威。迁移前先执行只读检查：

```bash
python3 scripts/app_layout_doctor.py --install-root /absolute/path --json
```

结果为 `mixed` 表示两种布局同时存在，必须通过显式迁移处理；入口和安装器不会
静默合并 release、session 或 workspace。只有在目录准备完毕后，才能写入
`etc/research-agent-layout.json` 标记；未标记的新布局也会被拒绝。
