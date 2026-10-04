---
name: script
description: 通过可审计的 Compute 生命周期运行声明输入和输出的受限 Shell 脚本。
---

# 脚本计算

使用本 Skill 时，需要标准 Attempt、Artifact 和 provenance 生命周期时，通过 `compute_run`
调用 `script.bash@1`。脚本必须作为不可变输入 Artifact，参数使用数组，
并在 `output_manifest` 中声明输出文件名；解析要求包含 `script_result.json`。

脚本在本地计算环境中执行，不能直接写入 Research State。Agent 读取结果后，
仍通过标准 Research State 操作登记科学事实。
