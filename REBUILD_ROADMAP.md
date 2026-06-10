# fiction_architect 全盘重构路线图

## 当前状态

### 第一阶段：已完成

- 主链路从旧 `batch/artifact/ref_pack` 转向 `active_chapter / chapter_task`。
- 建立生产状态机雏形：`task_ready -> drafting -> editorial_review -> rewrite_needed / editorial_passed -> human_release_check -> published -> canonized`。
- 修复目标字数、模型配置、线性续写、上一章上下文注入等关键问题。
- 明确 `chapter_batches` 只作为候选规划/兼容视图，不再作为正式生产真相源。

### 第二阶段：已完成

- 建立连续性账本、`chapter_draft`、`editorial_decision`、`rework_ticket`、`construction_packet v2`。
- 正式连续性只接受 `published/canonized` 正文，不接受 `draft/editor_approved/human_confirmed`。
- 新增 `chapter_state_snapshot`、`chapter_transition`、`official_canon`、`ledger_update_candidate` 和 `supersedes` 版本治理。
- `artifacts` 与旧 `ref_pack/author_brief/review artifact` 降级为历史兼容和调试归档，不再作为主生产输入输出。
- 连续性工作室页面开始转向账本视图：快照、正史、事实候选、账本候选与检索审计。

## 后续阶段

### 第三阶段：UI 与作家工作台重建

- 重建首页、单书工作台、章节生产页、连续性账本页，形成作家能长期维护一本书的主工作流。
- 单书工作台明确显示：当前 active chapter、候选章节、返工单、发布门禁、账本审批、导出状态。
- 修复页面嵌套、多次返回、保存后不刷新、生成进度静默等体验问题。
- 页面文案全部作者友好化，不暴露 `ref_pack`、`artifact`、`drafted` 等内部技术名，技术信息只放在调试展开区。

### 第四阶段：Planner / Outline Agent 重建

- 独立规划 Agent 负责卷纲、单元纲、章节施工卡，不再由普通章节生成链路临时拼模板。
- Planner 输入只读当前卷完整卷纲、前一卷/后一卷边界、当前单元、最近已发布状态变化。
- 章节施工卡必须给出具体剧情路线、人物职能、阻力变化、不可逆变化和结尾交接，禁止规则句和模板细纲。
- 规划失败时写入可读失败状态与模型调用日志，不产生污染正文的占位纲要。

### 第五阶段：Writer / Editor 质量治理

- Writer 只消费 `construction_packet`，不读取旧 `artifact/ref_pack/author_brief`。
- Editor 输出结构化返工单，明确 `route=planner/writer/human`，区分结构问题、连续性问题、文风问题和人工处理。
- 强化正文贴合检查：四级纲要、上一章结尾、人物状态、当前单元目标、已发布 transition 必须一致。
- 自动返工不超过设定轮次，超过后进入人工处理，不能继续污染连续性账本。

### 第六阶段：连续性长期生产能力

- 完成人物状态、关系状态、伏笔账本、设定硬事实、能力/职业/技术推进账本的审批、回滚和废弃流程。
- 实现季度/年度记忆与长期压缩版本治理，确保 100 章、1000 章时施工包大小不随章节数线性增长。
- 检索审计解释每条 snapshot、transition、atom、ledger entry 为什么进入本章施工包。
- 未批准事实、候选记忆、未来卷信息、未发布正文不得进入 Writer 输入。

### 第七阶段：发布、导出与运维稳定

- 完成 DOCX 导出版本治理、重新发布、撤回、废弃事件可视化。
- 加强 MySQL 长期运行 smoke、模型调用日志、失败重试、健康检查和错误页。
- 清理旧主路径残留：旧 `artifact/ref_pack/author_brief` 仅可历史查看，不能影响新章节写作。
- 每阶段结束前执行全量测试、敏感信息扫描和本地 Git 提交。

## 阶段验收原则

- 每阶段执行前后都跑全量单元测试。
- 每阶段至少增加对应防回退测试：
  - UI 不再显示旧主链路名。
  - Planner 不生成模板细纲。
  - Writer 不读取未发布正文。
  - Editor 不输出泛化审稿意见。
  - 连续性账本不接受 `draft/editor_approved`。
- 每次提交前确认 `.env`、数据库密码、API key、导出文件、上传文件不被 Git 跟踪。

## 默认约定

- 本路线图用于配合《fiction_architect 全盘重构研究报告》继续重构。
- 本地提交不自动推送 GitHub；远端推送只在明确要求时执行。
- 后续实现优先“大刀阔斧替换旧主路径”，只有轻微兼容和历史展示场景才保留旧对象。
