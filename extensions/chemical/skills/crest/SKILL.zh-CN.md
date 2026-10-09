---
name: crest
description: 运行和评估 CREST 构象搜索，并保存构象集合、能量、设置、来源与选择理由。
---

# TSPi CREST

[English version](SKILL.md)

使用本 Skill 通过已安装命令处理 CREST 构象搜索。CREST 负责构象集合探索；
CREST 搜索之外的 xTB 计算由 `xtb` 负责。

当前包没有内置 CREST runner。核实所选环境的命令和文档参数，可用时暂存通用
`job_start` 请求；Skill 缺少脚本本身不代表 CREST 不可用。

不要把进程正常退出或非空构象集合直接当作科学证据；必须先核对主要文件、成员数量和所选
结构身份。

绑定一个 XYZ Artifact，并显式给出电荷、未成对电子数、xTB 方法、搜索与优化级别、线程和
溶剂设置。核验正常终止与完整的主要输出集，检查构象数和能量表行数一致，并确保后续使用
的每个成员保持原子数、顺序与身份。

将集合大小、相对能量表、所选几何和选择理由记录为不同事实。调度器成功但缺失主要输出
属于运行故障，不是空构象集合。详见
[crest_ensemble.zh-CN.md](references/crest_ensemble.zh-CN.md)。

临时包装脚本通过通用准备器的 `--script` 和明确的 `--backend` 提交，见[方法选择](../method-selection/SKILL.zh-CN.md)。此路径记录脚本、环境、输入和输出。本 Skill 提供科学方法指导，当前没有内置该方法的执行入口。
