---
name: report
description: 根据科学 Skill 的结构化结果与来源摘要生成可核查的计算报告。
---

# 计算报告

先用 [scripts/prepare_job.py](scripts/prepare_job.py) 生成请求：

```bash
"$TSPI_PYTHON" scripts/prepare_job.py --result local=path/to/result.json --output prepared/report-job.json
```

调用时使用安装目录中的完整脚本路径；多个结果重复传入 `--result 环境名=路径`。准备脚本使用本地安装的 `TSPI_PYTHON`，声明需要暂存的报告脚本和结果文件，返回 `requestFile`、`requestSha256`。将这两个字段与报告的 `nodeId` 一起传给 `job_start`。报告节点必须已有策略且前置依赖满足。

Job 在隔离的 `runs/jobs/<job_id>` 中运行。命令和输出路径相对于 Job cwd；可选 cwd 只能是相对其根目录的子目录。输入源可以是绝对路径或工作区相对路径。不要把工作区绝对路径作为 cwd 或输出路径。准备脚本声明 `results/report.md`、`results/report.json` 为必需输出。输出目录可以不存在或为空，已有内容时拒绝覆盖；有意重跑时指定新的 `--work-id`。

收集 Job 输出并登记 Artifact。完成前核对用户要求的矩阵，解释失败和缺失单元。不同方法的绝对能量不能直接作为精度排名。只有用户要求通知时才使用 email Skill。
