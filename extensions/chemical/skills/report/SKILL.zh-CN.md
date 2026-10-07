---
name: report
description: 根据科学 Skill 的结构化结果与来源摘要生成可核查的计算报告。
---

# 计算报告

通过原生 bash 调用已安装的 [scripts/build.py](scripts/build.py)，设置合理超时：

```bash
"$TSPI_PYTHON" <已安装的报告Skill>/scripts/build.py --result local=<工作区>/path/to/result.json --output-dir <工作区>/reports/comparison-v1
```

以当前 Skill 的列出位置解析脚本。每份已收集的科学结果对应一个 `--result environment=path`。使用新的不存在或空输出目录，builder 拒绝覆盖已有文件。整理已有结果不创建 Job 或计算 Attempt；额外科学计算仍走 job_*。

读取 report.md 与 report.json，核对来源摘要及每个请求的方法/环境组合，再将两份文件登记为报告 Node 的 Artifact。说明失败或缺失结果，不能编造。不同方法的绝对能量不能作为准确性排名。通过 bash 使用 email Skill 完成用户要求的交付，关闭交付 Node 后再写最终 checkpoint。全局 blocked/terminal 时须先显式恢复 checkpoint 才能继续写入。
