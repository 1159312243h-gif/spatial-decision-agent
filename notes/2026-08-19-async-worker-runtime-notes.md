# 2026-08-19 异步 Worker 运行时说明

## 目标

把耗时的 GIS、POI、规则、解释和报告链路从 FastAPI 请求进程中移出。API 只负责请求校验、幂等占位、Redis 状态创建和 RQ 入队；独立 Worker 从队列取任务并复用现有 `SiteSelectionRunService` 执行。

## 调用边界

1. `POST /site-selection/runs` 调用 `prepare_run()`，写入 `queued` 状态和 `created` 事件。
2. `QueuedSiteSelectionRunService` 记录确定性的 `queue_job_id`，写入 `enqueued` 事件，再将业务请求放入 RQ。
3. API 返回 `202 Accepted`。这个状态不代表分析完成，也不包含分析、解释或报告。
4. Worker 从自己的环境装配 PostGIS、Redis、Fixture 与可选 LLM，强制使用同步执行器，避免任务再次入队。
5. Worker 将状态改为 `running`，执行原有 LangGraph 工作流，最终写入 `completed` 或 `failed`。
6. Workbench 显式刷新状态；只有 `completed` 才渲染候选对比、POI、证据和报告。

RQ 任务载荷只包含 `run_id` 和经过 Pydantic Schema 序列化的命令。数据库 URL、Redis URL 和 LLM 密钥均由 Worker 环境提供，不进入任务载荷或运行状态。

## 状态转换

```text
queued -> running -> completed
   |         |
   |         +-------> failed
   |         +-------> timed_out
   |         +-------> cancelled
   +-----------------> cancelled
   +-----------------> failed (enqueue failure)
```

幂等键重复提交同一请求时返回原 `run_id`，不会重复入队；同一幂等键对应不同请求仍返回冲突。

## 取消与超时

- 只有 `queued` 和 `running` 可以取消，重复取消幂等。
- 取消先写 Redis `cancelled` 终态，再调用 RQ 的 `job.cancel()` 或 `send_stop_job_command()`。
- `queued -> running`、运行终态和取消/超时均通过 Redis Lua 比较并更新，迟到请求不能覆盖已经变化的状态。
- 先写终态可以避免 Worker 停止回调抢先写成 `failed`；即使停止命令失败，迟到的 Worker 也会看到终态并停止发布结果。
- RQ `enqueue_call(timeout=...)` 是执行硬上限。超时失败回调只记录异常类型，并写入 `timed_out` 事件。
- 失败回调不会覆盖 `completed`、`failed`、`cancelled` 或 `timed_out` 终态。

取消不是数据库事务回滚。当前主要业务读取为只读，报告写入共享卷；后续增加外部写操作时必须单独设计事务或补偿。

## 配置

| 变量 | 默认值 | 作用 |
|---|---:|---|
| `SITE_SELECTION_RUN_MODE` | `sync` | 代码默认同步；Compose API 显式设为 `async` |
| `SITE_SELECTION_QUEUE_NAME` | `site-selection` | RQ 队列名称 |
| `SITE_SELECTION_JOB_TIMEOUT_SECONDS` | `180` | 单任务执行上限 |
| `SITE_SELECTION_JOB_RESULT_TTL_SECONDS` | `3600` | 成功任务结果保留时间 |
| `SITE_SELECTION_JOB_FAILURE_TTL_SECONDS` | `86400` | 失败任务记录保留时间 |
| `SITE_SELECTION_RUN_TTL_SECONDS` | `86400` | Redis 运行状态 TTL |
| `SITE_SELECTION_IDEMPOTENCY_TTL_SECONDS` | `86400` | 幂等记录 TTL，不得长于运行状态 |
| `SITE_SELECTION_POI_CACHE_TTL_SECONDS` | `3600` | POI 缓存 TTL |
| `SITE_SELECTION_EVENT_TTL_SECONDS` | `86400` | 运行事件 TTL，不得长于运行状态 |

## 验证范围

新增测试覆盖：API 进程不执行工作流、重复请求只入队一次、入队失败脱敏、queued/running 取消、完成后拒绝取消、Worker 执行、超时回调、取消终态保护、API `202/409/404`、Workbench 刷新/取消客户端以及六服务 Compose 契约。

当前独立测试区已通过 Python 语法编译。完整 pytest、RQ 真实 Redis Worker 和 Docker Compose 冒烟需要将增量复制到主项目、安装 `rq>=2,<3` 后执行，结果未在本说明中预设。

真实链路使用 `python .\scripts\smoke_day27_async_runtime.py` 验证 HTTP 202、异步事件链和共享 DOCX 报告。原 Day 24 Smoke 已兼容 `queued/running` 轮询。

### RQ 2.11 真实入队兼容修复

第一次 Docker Smoke 已到达 API，但 Worker 没有收到任务。Redis 中对应运行记录为 `queue_error_type=TypeError`，事件链为 `created -> enqueued -> failed`。根因是 RQ 2.11 的 `Queue.enqueue_call()` 使用参数名 `timeout`，适配器误传了不存在的 `job_timeout`。

适配器现已改用 `timeout`，并增加直接约束真实 RQ 适配器调用参数的回归测试，避免 Fake Queue 掩盖第三方 API 签名漂移。Day 24 和 Day 27 Smoke 也会输出阶段、HTTP 状态、run ID、终态、脱敏运行错误与事件类型，不输出凭据或原始任务载荷。

修复后独立测试区通过 16 个针对性测试和 451 个完整测试。复制覆盖包并重建 API/Worker 后，Day 27 真实异步 Smoke 已通过：`events=4`，共享 DOCX 报告可读取；Day 24 回归 Smoke 也通过 2 类项目、4 个候选、2 份报告与 6 个 MCP 工具验证。
