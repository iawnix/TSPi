# ASE NEB 可用性

当前包不提供已注册的 ASE NEB workflow 或内置 NEB runner，旧 `ase.neb@1` 接口不是可调用能力。
安装了 ASE 或找到 xTB/Gaussian，本身不代表已有可执行的 NEB 路径。

若所选环境提供有文档的 NEB 脚本，先核实其真实输入输出合同、calculator 绑定和依赖，
再通过 `job_start` 执行。否则实现并验证有界 runner，或选择保持科学目标的可用候选生成方法。
Skill 本地缺脚本不能证明共享 runner 或外部工具不存在；检查这些入口后再记录具体阻塞。

NEB 需要原子映射明确、顺序一致、电荷和电子态兼容的端点。显式记录端点松弛、插值、
image 数量、优化器、力阈值、calculator 设置和爬山图像策略，保存路径、各 image 能量和
收敛证据。最高能量 image 是候选结构，不是已验证过渡态。

现有执行入口见 [Gaussian Skill](../../gaussian/SKILL.zh-CN.md) 的显式 TS/扫描/QST 输入，
以及 [chemical-input](../../chemical-input/SKILL.zh-CN.md) 的分子种子准备；两者都不提供自动 NEB 或 TS 搜索管线。
