---
name: report
description: 根据科学 Skill 的结构化结果与来源摘要生成可核查的计算报告。
---

# 计算报告

通过 job_start 执行 [scripts/build.py](scripts/build.py)，用多个 `--result 环境名=路径` 传入结果，`--output-dir` 指定新的输出目录。结果文件作为 Job 输入暂存，report.md、report.json 声明为必需输出并登记 Artifact。完成前核对用户要求的矩阵，解释失败和缺失单元。不同方法的绝对能量不能直接作为精度排名。只有用户要求通知时才使用 email Skill。
