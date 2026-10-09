---
name: report
description: 根据研究证据编写图文报告，包含分子结构、能量曲线、数据表、方法、结论和可追溯的来源。
---

# 研究报告

围绕用户的研究问题写出结论、依据、方法和局限，使用用户要求的语言与交付格式。
完整研究报告应图文并茂：有结构证据时展示分子图，有可比能量时展示能量图，并用表格汇总数值与验证状态。
根据已有数据选择图表，不能为凑齐版式编造结构、路径、能量或误差。

先阅读[图表与报告制作](references/illustrated_report.zh-CN.md)，据此准备可重现的数据表、绘图脚本、
图片和最终文档。默认可交付 Markdown 与图片目录；用户要求 HTML/PDF 等格式时按可用工具导出。
必须在正文嵌入图表并写出图注，不能只提供图片路径清单。

## 基础数据表

对于 `science-result` 格式的已有结果，可通过原生 bash 调用 [scripts/build.py](scripts/build.py)：

```bash
"$RESEARCH_AGENT_PYTHON" <已安装的报告Skill>/scripts/build.py --result local=<工作区>/path/to/result.json --output-dir <工作区>/reports/comparison-v1
```

每份结果对应一个 `--result environment=path`，输出目录须不存在或为空。该脚本只生成
`report.md` 基础表格和 `report.json` 来源摘要；不会自动生成能量曲线、分子图或完整科学论述。
读取生成内容后补齐研究问题、证据分析、图表和结论。其他格式直接从已收集的材料建立报告数据集。

## 图像与交付

分子图可用 `chemical.render@1`，输入角色为 `geometry=<XYZ 文件>`，选择具有 `render` 绑定的环境。
该 Job 生成 SVG、PNG 和来源摘要，可设置 `--style`、`--size`、`--charge`、`--multiplicity`。
渲染只展示给定坐标；图像不能证明结构优化、连接关系或过渡态有效性。

整理已有结果可用文件和脚本工具；额外科学计算通过 `job_*` 执行。绘图需使用实际可用的绘图库，
渲染 Job 使用配置的环境。交付前打开最终文档与图像，核对链接、坐标轴、图注、单位、表格和来源。
将报告及依赖的图表、数据、脚本登记为材料，并在研究结论中引用。只有得到发送授权后才使用 email Skill 交付。
