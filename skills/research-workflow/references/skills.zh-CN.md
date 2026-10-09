# Skill 资源

Pi 加载已安装 Skill 描述，Agent 按需读取 SKILL.md。ResearchAgent 校验安装资源摘要。读取 Pi 提供的真实 Skill 路径，相对引用从该目录解析。

使用列出的准确资源名。引用不存在时检查当前 Skill 的 references 列表，不根据主题猜目录。反应映射说明位于 chemical-input Skill 目录下的 references/reaction_mapping.md。

参数错误或路径缺失是可修复的局部错误，阅读说明修正后重试，不能因此判断整个研究无法完成。软件失败与反驳科学假设的证据需要区分。
