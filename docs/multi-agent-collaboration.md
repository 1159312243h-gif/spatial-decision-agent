# 多 Agent 协作与自反思

该协作图由统一 Agent Harness 装配；Prompt 版本、上下文门禁、受控进化与专项评测见 [Agent Harness、受控进化与专项评测](agent-harness-evolution-evaluation.md)。

## 定位

多 Agent 协作层是确定性选址分析之后的可选复核阶段，不替代 GIS、POI、评分或规则引擎。它解决角色之间缺少消息、独立 Prompt、长期记忆、动态委派和自反思的问题，同时保留原系统的证据边界。

系统中存在两个职责不同的 Supervisor：

- `SiteSelectionSupervisor`：确定性流程控制器，负责候选发现、HITL 中断、异步分析提交、checkpoint 恢复和终态对账。
- `MultiAgentReviewRuntime` 中的 `SUPERVISOR`：LLM 协作角色，根据证据和历史消息动态委派 POI、Spatial、Policy Agent，证据充分后交给 Review Agent。

后者只能审查和升级风险，不能改变候选评分、排序、规则命中或合规状态。

## 执行链

```text
确定性分析完成
  -> Evidence Review 生成结构化质量问题
  -> LLM Supervisor 读取证据目录、角色记忆和最近消息
  -> 动态委派 POI / Spatial / Policy Agent
  -> 专家以自然语言回复，必须附已有 evidence_reference
  -> Supervisor 可继续委派，也可请求独立 Review
  -> Review Agent 接受 / 反驳并重新委派 / 转人工
  -> 达成接受，或在预算耗尽、协议违规、模型失败时 fail-closed
```

Review 的 `redelegate` 会把带理由的 Critique 消息送回 Supervisor。Supervisor 再根据全部对话选择专家，因此形成有界的“专家分析 -> 独立质疑 -> 再委派 -> 再复核”循环，而不是固定重试同一节点。

## 角色隔离

每个角色由独立的 `RoleAgent` 绑定：

- `AgentPromptProfile`：角色专属系统 Prompt、模型名、消息窗口和记忆窗口；
- `StructuredAgentModel`：角色可分别配置模型，也可共享同一 OpenAI-compatible 传输客户端；
- `AgentMemoryStore`：按 `memory_scope + role + memory_key` 隔离的长期记忆；
- 输出 Schema：Supervisor、专家和 Review 使用不同 Pydantic 契约。

当前默认 `memory_scope` 为 `project:<project_type>`，防止咖啡店、物流园等业态之间直接混用经验。Redis Store 使用 revision 做乐观并发校验；旧 revision 更新会触发 `AgentMemoryConflictError`，而不是覆盖新记忆。

## 消息和证据约束

`AgentMessage.content` 允许 Agent 间传递自然语言目标、发现和反驳；发送方、接收方、类型、轮次、时间和证据引用保持结构化。所有引用必须来自本次确定性分析生成的白名单，包括：

- `gis:<parcel>:<metric>`；
- `poi:<parcel>:<group>:<dataset>`；
- `rule:<rule>@<version>`；
- `review:<index>:<issue_code>`。

模型引用外部或不存在的事实会触发 `AgentProtocolViolationError`，协作报告进入 `failed` 并要求人工复核。协作结果存入 `AgentState.collaboration_report`，原业务状态只增加报告，不修改已有字段。

## 预算与终态

协作图同时限制：

- 最大动态委派次数；
- 最大 Review 自反思轮数；
- 最大 LLM 调用次数；
- 每个角色可读取的最近消息和长期记忆数量；
- 单次模型请求超时与 SDK 重试次数。

终态只有 `accepted`、`human_review`、`budget_exhausted` 和 `failed`。除 `accepted` 外都必须包含清洗后的人工复核原因，保证循环不会无限运行，也不会在模型异常时默认通过。

## 启用方式

该能力默认关闭。在 `.env` 中设置：

```dotenv
SITE_SELECTION_MULTI_AGENT_ENABLED=true
SITE_SELECTION_MULTI_AGENT_TIMEOUT_SECONDS=15
SITE_SELECTION_MULTI_AGENT_MAX_RETRIES=0
SITE_SELECTION_MULTI_AGENT_MAX_DELEGATIONS=6
SITE_SELECTION_MULTI_AGENT_MAX_REFLECTION_ROUNDS=2
SITE_SELECTION_MULTI_AGENT_MAX_LLM_CALLS=12
SITE_SELECTION_AGENT_MEMORY_TTL_SECONDS=2592000
```

所有角色默认使用 `LLM_MODEL`。需要独立模型时，分别设置：

```dotenv
SITE_SELECTION_SUPERVISOR_MODEL=your-planner-model
SITE_SELECTION_POI_AGENT_MODEL=your-poi-model
SITE_SELECTION_SPATIAL_AGENT_MODEL=your-spatial-model
SITE_SELECTION_POLICY_AGENT_MODEL=your-policy-model
SITE_SELECTION_REVIEW_AGENT_MODEL=your-critic-model
```

API 与 Worker 必须使用相同配置。异步模式下正式分析发生在 Worker，因此 Worker 未启用该开关时不会生成协作报告。

## 代码入口

- `practice/site_selection/agent_collaboration_contracts.py`：消息、记忆、委派、专家响应、Review 和终态契约；
- `practice/site_selection/agent_collaboration.py`：角色实例、OpenAI 适配器、Redis 记忆与 LangGraph 动态协作图；
- `practice/site_selection/parallel_workflow.py`：确定性 Review 后的可选协作入口；
- `app/site_selection_bootstrap.py`：环境变量、角色模型和 Redis Store 装配；
- `tests/test_agent_collaboration.py`：重新委派、证据边界、状态不可变和记忆冲突测试。

## 仍然保留的边界

这不是让多个 Agent 自由访问互联网或修改数据库的开放式群聊。专家 Agent 当前执行的是受约束证据分析任务；GIS、POI、政策检索和评分仍由既有确定性工具链完成。这样可以真实展示多 Agent 协作、动态委派和自反思，又不牺牲选址结果的可追溯性和可复现性。
