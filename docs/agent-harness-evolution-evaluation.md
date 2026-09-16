# Agent Harness、受控进化与专项评测

## 1. 能力边界

本项目把 Agent Harness 定义为多 Agent 协作图之外的统一运行外壳，负责版本、上下文、预算、门禁和 Trace。它不替代 LangGraph 业务 DAG，也不允许 LLM 修改 GIS、POI、规则、评分或排序结果。

“Agent 自进化”采用离线受控方案：Bad Case 只用于提出 Prompt 候选，候选必须在同一冻结集上与当前活动版本对照，通过质量与安全门禁，并取得人工批准后才能晋级。运行中的 Agent 不会自动修改源码、Prompt 或生产配置。

```text
确定性分析与 Evidence Review
  -> Agent Harness 结构化上下文投影/白名单门禁
  -> 解析活动 Prompt 版本
  -> Supervisor/POI/Spatial/Policy/Review 协作图
  -> 预算终态 + Harness Trace

Bad Case/人工标注
  -> 离线 Prompt 候选
  -> 同一冻结集 Baseline/Candidate 对照
  -> 质量、安全、成本门禁
  -> 人工批准
  -> 不可变版本晋级
  -> 可审计回滚
```

## 2. Harness 负责什么

`practice/site_selection/agent_harness.py` 提供以下职责：

- `PromptBundle`：五个角色的 Prompt、模型与消息窗口作为一个不可变版本；禁止只升级单个角色却丢失整体依赖。
- `PromptVersionRegistry`：注册候选、解析活动版本、记录人工批准引用和回滚事件。
- `AgentHarness`：从完整 `AgentState` 投影出紧凑结构化证据，检查字符数与引用数，再创建当前版本的协作 Runtime。
- `AgentHarnessReport`：记录 Harness/Prompt 版本、上下文规模、委派/反思/LLM 预算、阶段 Trace 和明确终态。

上下文不是把整个会话原文直接塞给模型。正式分析首先以不可变 `ScenarioVersion` 为准；进入协作层时只投影请求、候选证据、比较结果、Evidence Review 问题和允许引用的 ID。每个角色再按自己的 `memory_limit` 与 `message_limit` 读取角色记忆和最近消息。若投影上下文超过 Harness 门槛，系统在调用 LLM 前 fail-closed。

## 3. 受控进化如何工作

`practice/site_selection/agent_evolution.py` 实现五步闭环：

1. `propose_candidate` 基于当前活动版本只修改指定角色 Prompt，并保存父版本、假设和生成来源。
2. Baseline 与 Candidate 必须使用相同 `suite_id@suite_version`，避免换题后制造提升。
3. `PromotionPolicy` 同时检查任务成功率、证据引用合规率、预算收敛率、协议违规检测率和平均 LLM 调用增幅。
4. `promote` 只接受通过门禁的 `decision_id`，并强制要求非空人工批准记录。
5. `rollback` 同样要求人工批准，生成独立审计事件并恢复指定稳定版本。

默认门禁要求 Candidate 冻结案例全部通过，任务成功率和反思恢复率不得相对 Baseline 下降，证据引用合规、预算收敛和协议违规检测全部达到 100%，且平均 LLM 调用数最多增加 1 次。不同生产场景可以收紧门槛，但不应通过放宽期望来“优化”评测结果。

当前实现属于 Prompt/策略级受控进化，不是模型权重在线训练，也不是无人监督自改代码。活动版本由运行进程中的注册表解析，并通过环境变量固定部署版本；将来若接入持久化 Prompt Registry，仍应保留相同的评测和人工批准接口。

## 4. 专项评测

`evals/agent-cases.json` 冻结 6 个协议案例：

| 案例 | 验证目标 |
|---|---|
| `AGENT-001` | 证据充分时直接 Review 并接受 |
| `AGENT-002` | Supervisor 委派 POI Agent 后收敛 |
| `AGENT-003` | Critic 反驳、重新委派 Spatial Agent 后恢复 |
| `AGENT-004` | 未知证据引用被检测并 fail-closed |
| `AGENT-005` | 证据边界不足时主动转人工 |
| `AGENT-006` | 反思预算耗尽时进入明确终态 |

运行：

```powershell
python .\scripts\run_agent_evaluations.py
```

结果写入 `evals/results/agent-summary.json`，输出：

- `task_success_rate`：目标为接受的正常案例中，最终成功接受的比例；
- `evidence_reference_valid_rate`：报告消息引用是否全部属于本次证据白名单；
- `reflection_recovery_rate`：需要 Critic 反驳的正常案例中，经补充委派后接受的比例；
- `human_escalation_rate`：明确进入人工复核的案例比例；
- `budget_convergence_rate`：在委派、反思和 LLM 调用预算内进入终态的比例；
- `protocol_violation_rate`：整个对抗性套件中触发协议违规的案例比例；
- `protocol_violation_detection_rate`：预设违规案例被正确检测的比例；
- `average_llm_calls`、`average_delegations`：质量之外的成本指标。

内置脚本使用可复现的 Scripted Model，只证明 Harness 路由、协议和门禁行为，不代表真实模型质量。Prompt 晋级前还必须用固定模型参数、固定证据输入和人工标注期望执行真实 Baseline/Candidate A/B 评测；不能把 `6/6` 写成生产任务成功率。

## 5. 关键文件

- `practice/site_selection/agent_harness_contracts.py`：Harness 报告契约；
- `practice/site_selection/agent_harness.py`：统一运行外壳与 Prompt 版本注册表；
- `practice/site_selection/agent_evolution.py`：候选、门禁、批准、晋级和回滚；
- `practice/site_selection/agent_evaluation.py`：多 Agent 冻结评测与指标聚合；
- `evals/agent-cases.json`：版本化协议案例；
- `scripts/run_agent_evaluations.py`：离线评测入口；
- `tests/test_agent_harness.py`、`tests/test_agent_evolution.py`、`tests/test_agent_evaluation.py`：回归测试。
