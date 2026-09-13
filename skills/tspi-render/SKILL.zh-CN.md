---
name: tspi-render
description: 将分子结构、轨迹、反应机理和科学曲线渲染为 TSPi 图像与动画。
---

# TSPi 渲染

[English version](SKILL.md)

使用本 Skill，通过 `ts_render` 将结构和数值数据制作成图像。
工作区和产物操作使用 `tspi-orchestration`。

## 选择输出

| 操作 | 输入 | 输出 |
| --- | --- | --- |
| `render` | 一个分子结构 | PNG 分子图 |
| `animate` | 一份轨迹 | GIF 动画 |
| `compare` | 两个或更多结构 | PNG 结构对比图 |
| `mechanism` | 按反应物、过渡态、产物排序的三个结构 | PNG 反应示意图 |
| `curve`、`energy`、`scan`、`convergence` | 一个 `ts-curve-data/1` JSON 产物 | PNG 科学曲线图 |

## 渲染流程

1. 通过 `ts_state mode=artifacts` 查询已注册的输入 ID。
2. 选择操作、所属 ResearchNode、输入顺序，以及带有相应扩展名的新输出文件名。
3. 绘制曲线时，对照源数据核验序列名称、坐标轴标签、单位和数值，明确能量参考点
   和扫描坐标。
4. 运行 `ts_render`，检查图像、返回的产物 ID 和摘要。
5. 将科学数值记录为引用已核验源产物的 Observation；在回复或 `tspi-report`
   报告中使用生成的图像。

分子渲染使用 `xyzrender`，曲线渲染使用 Matplotlib。
输入格式、曲线示例、输出路径和错误处理见[渲染参考](references/render_contract.md)。
