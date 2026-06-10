# fiction_architect 全盘重构路线图

## 当前状态

### 第一阶段：已完成

- 主链路从旧 `batch/artifact/ref_pack` 转向 `active_chapter / chapter_task`。
- 建立生产状态机雏形：`task_ready -> drafting -> editorial_review -> rewrite_needed / editorial_passed -> human_release_check -> published -> canonized`。
- 修复目标字数、模型配置、线性续写、上一章上下文注入等关键问题。
- 明确 `chapter_batches` 只作为候选规划或历史兼容视图，不再作为正式生产真相源。

### 第二阶段：已完成

- 建立连续性账本、`chapter_draft`、`editorial_decision`、`rework_ticket`、`construction_packet v2`。
- 正式连续性只接受 `published/canonized` 正文，不接受 `draft/editor_approved/human_confirmed`。
- 新增 `chapter_state_snapshot`、`chapter_transition`、`official_canon`、`ledger_update_candidate` 和 `supersedes` 版本治理。
- `artifacts` 与旧 `ref_pack/author_brief/review artifact` 降级为历史兼容和调试归档，不再作为主生产输入输出。

### 第三阶段：已完成

- 重建书架、单书工作台、规划台、写作台、发布中心。
- 单书首页直接显示 active chapter、候选章节、返工单、发布门禁、最近 canon 和待审批账本。
- 规划、写作、发布动作均提供进度条和下一步入口。
- 普通页面不再暴露 `ref_pack`、`author_brief` 等旧主链路技术名。

### 第四阶段：已完成

- 新增 `workflow` 层，统一管理 `create_book_flow`、`plan_next_chapter_flow`、`draft_next_chapter_flow`、`review_next_chapter_flow`、`rework_flow`、`publish_flow`。
- Planner 生成候选章节施工卡，通过 schema gate 后进入 `chapter_candidates`。
- `chapter_batches` 被降级为候选窗口和历史兼容层，不能绕过 active chapter 门禁。
- 规划失败写入 workflow run/event，不再生成污染正文的占位细纲。

### 第五阶段：已完成

- Writer 主路径只消费 `construction_packet`，输出 `chapter_draft`。
- Pipeline 变为兼容外壳，旧 route 仍可用，但实际委托给 `WorkflowKernel`。
- Editor 输出结构化 `editorial_decision` 和 `rework_ticket`，包含 `status`、`score`、`failure_codes`、`evidence`、`route`、`required_fixes`。
- 自动返工由 workflow 管理，正式下一章必须等待上一章发布门禁。

### 第六阶段：已完成基础骨架

- 连续性工作室转为账本视图：snapshot、transition、official canon、atom、ledger candidate、retrieval audit。
- `construction_packet` 只读取 published/canonized snapshot、transition、approved/published atom、当前单元状态、style pack。
- 新增 workflow/event/export version 表，为季度/年度记忆和 100/1000 章预算测试预留治理接口。
- 未批准事实、候选记忆、未发布正文、未来卷信息不得进入 Writer 输入。

### 第七阶段：已完成基础骨架

- DOCX 导出进入 export version 治理；导出后发布写回 canon。
- 新增 workflow run/event 记录，便于失败重试、健康检查和模型调用排查。
- 旧 `artifact/ref_pack/author_brief` 主路径被测试约束为不可影响新章节写作。
- 本轮保留 FastAPI + SQLite/MySQL + VSCode 直接运行能力，不引入 Temporal、LangGraph 或 Node SPA。

## 本轮之后可继续深化项

- UI 深化：连续性账本的审批、废弃、回滚操作需要更完整的可视化批处理。
- Planner 深化：卷纲、单元纲、章节施工卡可进一步拆成独立 agent activity，并增加更严格 JSON schema 校验。
- Editor 深化：增加 LLM-as-editor 深审、重复功能检测、人物职能漂移检测和平台化审稿模板。
- 长期记忆：补齐季度/年度记忆后台 consolidation，并做 100 章/1000 章 packet 预算压力测试。
- 运维：补 MySQL 长跑 smoke、模型调用日志页、失败重试队列、健康检查页和敏感信息扫描命令。

## 验收原则

- 每次重构提交前运行 `python -B -m unittest discover -s tests -t .`。
- 主流程不得依赖旧 `batch/artifact/ref_pack` 作为业务真相。
- Writer 不得读取 `draft/editor_approved/candidate/future volume`。
- 正式连续性只信任 `published/canonized`。
- `.env`、API key、数据库密码、数据库文件、上传封面、导出 DOCX 不得被 Git 跟踪。
