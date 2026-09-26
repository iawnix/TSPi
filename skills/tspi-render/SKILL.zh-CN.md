---
name: tspi-render
description: 将分子结构、轨迹、反应机理和科学曲线渲染为 TSPi 图像与动画。
---

# TSPi 渲染

[English version](SKILL.md)

使用 `artifact_render` 将已注册结构和数值 Artifact 制作成图像；Node 所属和 map 变更使用
`tspi-research-kernel`。

不要把渲染图像当作新的科学证据。引用到 Finding 前必须核对来源 Artifact、标签、单位和
ResearchMap revision。

| 操作 | 输入 | 输出 |
| --- | --- | --- |
| `render` | 一个分子结构 | PNG |
| `animate` | 一份轨迹 | GIF |
| `compare` | 两个或更多结构 | PNG 对比图 |
| `mechanism` | 反应物、过渡态、产物 | PNG 示意图 |
| `curve`、`energy`、`scan`、`convergence` | `ts-curve-data/1` JSON | PNG 曲线 |

通过 `research_read mode=artifacts` 找到输入，选择所属 Node 和安全的输出名，运行
`artifact_render` 并检查返回 Artifact 与摘要。核对标签、单位、参考点和源数据；只有核验过的
科学数值才记录为 `FactFinding`。详见
[渲染合同](references/render_contract.zh-CN.md)。
