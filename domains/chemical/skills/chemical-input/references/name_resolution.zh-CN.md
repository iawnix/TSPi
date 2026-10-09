# 名称解析

按 Skill 中的通用准备命令生成 chemical.resolve@1 Job，传 --name 原文；可加 --lookup-name 规范化名称。
全局参数 --output 指定 JSON，--config 指定绝对路径的名称解析 TOML。
默认依次读取 RESEARCH_AGENT_NAME_RESOLVER_CONFIG 或 RESEARCH_AGENT_INSTALL_ROOT/etc/name-resolver.toml。
支持已启用的 PubChem、OPSIN 后端，保存请求来源、时间、响应摘要和候选。
中性水使用有版本的内置规则，无需网络。HTTP 404、限流和网络错误保留诊断。
resolved 表示唯一确定性候选；ambiguous 表示多个候选或未指定立体化学；
draft 表示未经确认的模型候选；unresolved 表示无可用结果。
可对研究范围内的立体异构体显式枚举；不要将网络失败解释成化学结构不存在。
