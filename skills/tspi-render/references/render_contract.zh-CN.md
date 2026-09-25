# 渲染合同

`artifact.render` 将分子图像、动画、比较面板、反应图和科学曲线创建为本地 Artifact。

请求选择 `render`、`animate`、`compare`、`mechanism`、`curve`、`energy`、`scan`
或 `convergence`，以及一个已有 ResearchNode、逻辑输入 Artifact ID 和安全输出文件名。
Host 解析路径/摘要并拥有：

```text
nodes/<node_id>/outputs/render/<outputName>
```

使用已注册 workspace Artifact、operation 要求的输入数量，以及新文件名：动画以 `.gif`
结尾，其他 operation 以 `.png` 结尾。Host 检查路径 containment、文件类型、输入可用性与
输出名称。成功的 Backend 生成非空普通 PNG/GIF，其摘要通过 Artifact catalog 返回。

曲线 operation 准确需要一个符合 `ts-curve-data/1` 的 JSON 输入，并始终生成 PNG。
Artifact 包含 1 到 16 个 series，每个 series 的有限 `x` 与 `y` 数组长度相等，最多
100,000 个点。

例如，scan-data Artifact 可以包含：

```json
{
  "schema_version": "ts-curve-data/1",
  "title": "Bond-distance scan",
  "x_label": "C-C distance (angstrom)",
  "x_unit": "angstrom",
  "y_label": "Energy relative to first point (kJ/mol)",
  "y_unit": "kJ/mol",
  "series": [{"name": "Scan", "x": [1.5, 1.8, 2.1], "y": [0.0, 12.5, 30.2]}]
}
```

这些数值只用于说明数据格式。实际研究必须使用已核验计算输出中的值，并保留单位与参考
能量。为 `scan` 选择已注册 JSON Artifact ID 作为输入；`curve`、`energy` 与
`convergence` 接受相同数据格式。

分子 operation 使用 `xyzrender`，曲线 operation 使用 Matplotlib。Schema 见
[curve-data.schema.json](../../../contracts/ts-render/curve-data.schema.json)。

渲染用于检查几何、比较结构、制作模式动画或表达机理。成键变化、端点 identity 与模式
归属应根据对应结构和计算数据建立。将已核验值记录为引用主要来源 Artifact 的 Finding。
