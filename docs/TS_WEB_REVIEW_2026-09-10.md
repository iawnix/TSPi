# ts_web 界面优化与验收报告

日期：2026-09-10
范围：`packages/ts-agent-kernel/ts_agent/web/`、`packages/ts-agent-kernel/ts_agent/web/static/`、`tests/test_ts_web.py`。界面结论来自源码、真实工作区投影和 Chromium/ChromeDriver 走查；截图只用于检查视觉布局。

## 结论

`ts_web` 需要优化，但不需要推倒重做。原实现的数据流、只读权限边界和主要视图都成立，主要问题是研究前沿不够突出、状态语义分散、品牌资产不完整、界面字符串缺少统一双语层。

本轮已完成这些核心优化。Web 仍然只读取 Research Kernel 投影，没有新增第二套研究状态，也没有把 UI 状态当成科研证据。

## 1. 研究过程可视化

已完成：

- 首页增加“研究前沿”卡片，直接显示当前 ResearchNode、目标、状态、Claim 范围和详情入口。
- 首页增加统一状态图例，以文字和颜色共同表达 `supported / proposed / open / warning / blocking`。
- 标题区域显示实时刷新状态、最近快照时间、workspace revision 和 operational revision。
- 保留 Research Map 与 Dependency DAG 两种投影；前者用于阅读阶段和假设分支，后者用于审计依赖关系。
- Scientific Conclusions 保留表格与关系图两种模式；关系图可按状态、类型和接受状态过滤。
- 390 px 窄屏下，DAG 与 Claim Map 自动切换为可滚动的结构化大纲，避免在触屏设备上强行缩放画布。

这些内容都来自同一个 workspace snapshot。前沿、摘要、图例和图关系是派生显示，不写回 canonical state。

## 2. UI 设计与色彩

现有 light/dark token 体系继续作为基础。本轮新加入的前沿卡片、快照元数据、图例、Logo 和交互状态复用了同一语义色：

| 语义 | 颜色与辅助编码 |
| --- | --- |
| 当前研究、投影、选择 | Teal / Cyan，左边框或实心圆 |
| 已支持、健康 | Green，状态文字 |
| 开放、待验证 | Blue / Cyan，状态文字 |
| 过期、警告 | Amber，警告文字 |
| 阻塞、失败 | Coral / Red，错误文字与边框 |
| Claim 关系、来源 | Violet，关系标签或连线 |

暗色与亮色模式都保持卡片、背景、分隔线和正文的层级差异。桌面截图中没有发现文字裁切、卡片重叠或横向溢出；390 px 页面宽度检查为 `clientWidth = scrollWidth = 390`。

## 3. 交互

已验证的主要路径：

- 六个主导航视图可以切换并保留正确的 active 状态。
- `/`、`Ctrl+K`、`Cmd+K` 可聚焦当前视图搜索框。
- Research Map / Dependency DAG、Conclusions Table / Map 可以切换。
- Claim Map 的三个筛选器以及 Claim Map、DAG 的聚焦、缩放和适配控件具备可见标签或 ARIA 名称。
- ResearchNode 详情可打开 Overview、Conclusions、Evidence、Runs、Files、History；Runs 能定位 `calc_1`，History 能显示决策历史和审计引用。
- 详情抽屉可以通过关闭按钮、遮罩和 Escape 关闭；390 px 下抽屉宽 374.39 px，右边界与 390 px 视口一致。
- 刷新按钮在刷新期间使用等待光标；真正不可用的按钮使用 `not-allowed` 光标。

窄屏导航保留为横向滚动条，主内容不产生页面级横向溢出。DAG 和 Claim Map 的触屏大纲仍可打开同一套详情。

## 4. Logo 与产品协调

已新增并接入：

- `packages/ts-agent-kernel/ts_agent/web/static/logo.svg`
- `packages/ts-agent-kernel/ts_agent/web/static/favicon.svg`

Logo 使用深墨底、Teal 的 `TS/π` 几何和 Amber 反应路径，缩小到 favicon 尺寸仍能辨识。网页页眉、favicon 和本轮论文架构图使用同一组深墨、Teal、Amber 配色。

TS Phone 由独立源码仓库维护，本轮没有跨仓库替换其 Android/iOS 图标。若需要整套产品在应用商店、安装包、报告封面和网页上使用同一几何，应在 `ts-phone` 仓库单独同步并走移动端构建验证。

## 5. 中英文与明暗切换

已完成：

- 新增独立 `i18n.js` 词典层，中英文各 401 个键，键集合一致。
- 语言选择保存到 `localStorage`，刷新后继续生效。
- 切换语言会同步更新 `<html lang>`、页面标题、导航、视图标题、筛选器、表头、状态、空状态、错误信息、详情页、tooltip 和 ARIA 文案。
- Claim statement、Claim type、relation type、科学说明、文件路径和用户产生的原始数据保持原文，不进行伪翻译。
- 明暗主题继续持久化，主题按钮的图标、title 和 ARIA 文案随当前语言和下一主题同步变化。
- 自动化测试检查双语键完全一致，并覆盖所有静态 `tr(...)` 与 `data-i18n-*` 字面量引用。

## 6. 虚假按钮

源码审查与浏览器走查没有发现无行为的装饰按钮：

- 顶栏语言、主题、刷新和工作区选择器都有实际状态变化或数据请求。
- 主导航、模式切换、图控件、筛选器、详情入口、详情标签页、文件预览和关闭控件都有事件处理。
- Claim/Node 卡片是详情入口；普通关系说明和状态标签没有伪装成按钮。
- 图视图在移动端隐藏不适合触屏的缩放按钮，同时提供结构化大纲，不留下不可用占位控件。
- 当前工作区中可见按钮均有可见文本、title 或 ARIA 名称。

因此，本轮没有删除所谓“假按钮”；实际修正集中在禁用态语义、可访问名称和移动端控件降级。

## 浏览器验收

| 场景 | 结果 |
| --- | --- |
| 1440 × 957，中文，暗色 | 通过；Research Map、前沿、摘要和状态图例无重叠 |
| 1440 × 957，中文，亮色 | 通过；文本、边框和状态色层级清楚 |
| 中英文切换 | 通过；Conclusions、Validation、Findings、Activity 表头和标题同步更新 |
| Claim Map | 通过；筛选、ARIA、关系选择和详情入口正常 |
| Dependency DAG | 通过；阶段选择、聚焦、缩放、适配和详情入口正常 |
| Node Runs / History | 通过；Attempt 家族、`calc_1`、决策历史和审计引用可读 |
| 390 × 844，中文，暗色 | 通过；页面无横向溢出，DAG/Claim Map 使用大纲，详情抽屉适配视口 |
| 语言和主题持久化 | 通过；`localStorage` 状态与 DOM 状态一致 |

## 后续可选项

当前版本已经满足本轮六项优化目标。后续若面向更复杂工作区，可继续增加：

- 详情抽屉中的面包屑和跨记录返回栈。
- 专门的打印样式以及 SVG/CSV 导出入口；只有接入真实导出后才显示按钮。
- 全局命令面板，用一个入口定位视图、Claim、Node、Attempt 和 Finding。
- TS Phone、报告封面与安装包图标的跨仓库品牌资产同步。
