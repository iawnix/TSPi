# 反应映射 Capability

已注册机理分析 `reaction.mapping.validate@1` 校验 Root 提供的 mapping，不会自行发明
原子映射。

## 发现与调用

```text
research.read mode=capabilities capabilityKind=analysis
research.read mode=capabilities capabilityKind=analysis query=reaction.mapping.validate@1
```

调用 `analysis.run` 时提供未关闭的 `nodeId`、已注册 XYZ Artifact ID 和显式、从零开始的
mapping。请求中不能出现物理路径。Species index 指向列表位置；重复 Artifact ID 表示同一
species 的不同 occurrence。遵守 capability 返回的限制。

## 结果

结果包含一个分析 Artifact，以及 validity、coverage、计数、诊断、来源 ID 与摘要的概览。
有效 map 必须准确覆盖两侧每个原子一次、元素匹配，并保持整个反应的元素计数。没有矛盾的
部分 map 属于 inconclusive；重复引用、错误元素、计数不等或空 map 属于 invalid。

当结果支持科学陈述时，通过 `research.change` 创建 `FactFinding`，提供产出它的 `node_id`、
简洁 statement、`kind=fact`、相关 value 与 datatype，并在 `source_refs` 中引用分析
Artifact。不完整或化学上有歧义的 map 记录为 `IssueFinding`。不要把解析器诊断复制到
map 并当作事实。

## 局限

该 capability 不判断成键变化是否化学合理、质子是否隐式、对称等价 map 是否等价，也不
判断过渡态是否到达端点。XYZ 本身不能建立同位素、电荷、自旋或键 identity；结构比较、
端点验证与过渡态验证应分别使用对应 Skill。
