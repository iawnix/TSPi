# CF22D 工作流

scripts/run.py 接收 angstrom 单位的 XYZ、电荷、PySCF spin（2S）、基组、网格、SCF 收敛设置、优化步数、线程和内存；以 --help 为准确参数表。--xc 只接受 CF22D。默认网格 6、SCF 阈值 1e-10、400 步、def2-tzvp；比较任务必须显式指定用户要求的基组。

支持 sp、opt、opt-sp、ts、freq、thermo、opt_freq、ts_freq。opt-sp 分成 opt/sp 目录，SP 输入摘要绑定优化后结构。历史 opt runner 自身也执行最终 SCF，但不替代 opt-sp 的显式单点。频率与热化学需要 SCF 收敛。TS 默认启用初始 Hessian，可显式关闭。

输出目录必须新建且为空。顶层 result.json、geometry.xyz 汇总结果；每步保存 pyscf.out、pyscf_result.json 和需要的几何、频率、Hessian、热化学产物。scratch 保留在尝试目录中用于诊断，进程结束后可清理该子目录，不删除安装级 scratch 根目录。脚本和输入摘要绑定结果，脚本不写 Research Memory。

检查 execution_completed、SCF 收敛、结构化优化收敛证据和任务产物，保存单位与实际版本。拒绝非有限能量及不匹配的方法/基组/输入。研究记录和证据由 Agent 登记。

频率计数不是振动模式归属、端点身份或 IRC。显著虚频阈值默认 -20 cm^-1，没有频率计算不能宣称已验证极小值。此 runner 不实现 IRC、NEB、反应扫描、交叉点或多结构比较；不能用 RHF/其他泛函替代缺失能力。
