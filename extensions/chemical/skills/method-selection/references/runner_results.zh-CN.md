# 科学 runner 结果

CF22D、xTB 和 Gaussian 输出 `science-result/2`。`checks_passed` 表示
runner 完成了请求的数值和输出检查，不代表极小值、鞍点、机理或用户要求已经
得到确认。`scientific_validation` 保持 `not_assessed`，科学评估由验证器
和 Research State 分别记录。执行与收集状态以 Job 回执为准，保留失败结果
和原始日志，不改写结果来提升判定。

坐标单位为 angstrom，电子能量为 hartree，其它量的字段名标明单位。公开参数
统一使用整数电荷和 `--multiplicity`（2S+1，默认 1）。runner 检查 XYZ 的
电子数奇偶关系，再转换为 PySCF spin 或 xTB 未配对电子数。破缺对称态等不能
仅由此约定确定的电子态，需要明确支持的方法或输入，不能只凭多重度推断。

`opt-sp` 的单点使用优化后的结构。核对 SP 输入摘要与优化结构摘要一致，且两个
步骤均完成。独立提交的优化与单点通过明确的 Artifact 依赖关联。

准备命令负责暂存固定摘要的脚本和执行入口声明的输出。Agent 提供科学输入及
参数，再用返回的请求文件和摘要调用 `job_start`。环境不可用表示能力尚未就绪，
不能据此静默替换方法。目标选择见[运行环境](runtime_environment.zh-CN.md)。

报告整理源文件并保留摘要。历史 `science-result/1` 的 `validated` 含义不一致，
报告将其检查状态保留为未知，不把 runner 标记转成科学验收。
