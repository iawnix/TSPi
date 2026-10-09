---
name: report
description: 根据已有科学结果生成可核查的计算报告，或将给定 XYZ 几何渲染成 SVG 与 PNG 图像。
---

# 计算报告

通过原生 bash 调用已安装的 [scripts/build.py](scripts/build.py)，设置合理超时：

```bash
"$RESEARCH_AGENT_PYTHON" <已安装的报告Skill>/scripts/build.py --result local=<工作区>/path/to/result.json --output-dir <工作区>/reports/comparison-v1
```

以当前 Skill 的列出位置解析脚本。每份已收集的科学结果对应一个 `--result environment=path`。使用新的不存在或空输出目录，builder 拒绝覆盖已有文件。整理已有结果不创建 Job 或计算 Job；额外科学计算仍走 job_*。

读取 report.md 与 report.json，核对来源摘要与每个请求的方法/环境组合，再登记为材料。说明失败、缺失结果和方法限制；不能把跨方法绝对能量当作准确性排名。通过 email Skill 完成已授权交付，保存回执并用 research_update 记录进度。

分子图像使用 `chemical.render@1`，输入角色为 `geometry=<XYZ 文件>`，选择配置了 `render` 绑定的环境。声明入口通过 Job 生成 SVG、PNG 和来源摘要记录。可选参数为 `--style`、`--size`、`--charge`、`--multiplicity`；渲染使用给定坐标。图像不能证明优化、连接关系或过渡态有效性。前述文本报告整理不依赖渲染环境。
