# 数据字典

## 1. 领域输入

### `ProjectRequest`

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| `request_id` | string | 非空 | 单次分析请求标识 |
| `project_type` | enum | `coffee_shop` / `convenience_store` / `shopping_mall` / `logistics_park` | Profile 路由键 |
| `analysis_scope` | enum | `market_selection` / `full_compliance`，默认后者 | 市场选址分析或完整合规分析；前者当前仅支持零售 |
| `candidate_parcels` | array | 至少 1 个，`parcel_id` 唯一 | 候选地块 |
| `requested_at` | datetime | 必须含时区 | 请求时间 |

### `CandidateParcel`

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| `parcel_id` | string | 非空 | 候选地业务标识 |
| `name` | string/null | 可选 | 展示名称 |
| `longitude` | float | `[-180, 180]` | WGS84 经度 |
| `latitude` | float | `[-90, 90]` | WGS84 纬度 |
| `area_hectares` | float/null | 大于 0 | 可选外部面积；正式分析优先使用 GIS 证据 |
| `geometry_dataset_id` | string/null | 前置检查要求存在 | 指向 `DatasetManifest.dataset_id` |

### `DatasetManifest`

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| `dataset_id` | string | 唯一、非空 | 数据集标识 |
| `name` | string | 非空 | 展示名称 |
| `source` | enum | `api` / `postgis` / `file` | 来源类型 |
| `location` | string | 不含密钥 | 表名、文件路径或 API 资源标识 |
| `version` | string | 非空 | 可复现版本 |
| `crs` | string/null | 空间分析要求存在 | 源坐标系 |
| `evidence_level` | enum | `unspecified` / `authoritative` / `public_observation` / `synthetic` | 数据能支持的证据等级 |
| `source_uri` | string/null | 不包含凭证 | 原始目录、服务或登记来源 |
| `license` | string/null | 权威/公开源要求存在 | 授权或开放数据许可 |
| `required_fields` | array | 非空、去重 | 数据校验字段 |
| `updated_at` | datetime | 必须含时区 | 数据更新时间 |

### `CandidateDiscoveryRequest`

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| `project_type` | enum | 咖啡店或便利店 | 候选发现 Profile |
| `bounds` | object | WGS84、对角线不超过 20 公里 | 发现范围 |
| `max_candidates` | int | 3 到 20 | 最大返回候选数 |
| `minimum_separation_m` | int | 100 到 5,000 | 候选空间去重距离 |
| `fallback_mode` | enum | `strict` / `commercial_land_proxy` / `market_exploration` | 用地不足时的最大允许降级层级 |
| `range_poi_limit` | int | 100 到 5,000 | 范围背景 POI 响应上限，不影响评分查询上限 |

### `CandidateDiscoveryReport`

| 字段 | 类型 | 含义 |
|---|---|---|
| `strategy` | enum | 实际使用的 `registered_land`、`public_land_observation`、`commercial_land_proxy` 或 `market_exploration` |
| `land_evidence_level` | enum | 权威、公开观察、合成演示或暂无依据 |
| `land_source_uri` | string/null | 用地原始来源或服务地址 |
| `land_source_license` | string/null | 数据许可或授权说明 |
| `land_source_cache_hit` | boolean | 本次公开用地是否命中 Redis 缓存 |
| `formal_analysis_allowed` | boolean | 是否具备执行 GIS/政策合规审查的用地依据；为假不再阻断零售商业选址分析 |
| `evaluated_candidate_count` | int | 进入评分的机会单元数 |
| `excluded_by_land_use_count` | int | 在评分前被用地类别排除的单元数 |
| `candidates` | array | 排序、去重后的候选或市场机会网格 |
| `sources` | array | POI Provider、数据集、截断、合成和降级来源 |
| `range_pois` | array | 矩形范围内、按 Provider 与 POI ID 去重的背景 POI，不参与评分 |
| `range_poi_observed_count` | int | 应用响应上限前实际观察到的去重记录数 |
| `range_poi_is_truncated` | boolean | Provider 或响应上限是否可能导致范围记录不完整 |
| `sources[].fallback_reason` | string/null | 新报告记录在线降级原因；旧 Supervisor checkpoint 允许为空以兼容恢复 |
| `warnings` | array | 数据边界和人工核验提示 |
| `confirmation_required` | boolean | 当前固定为真，候选分析前必须确认 |
| `execution_plan`, `agent_trace` | object/array | 候选发现 Agent DAG 与节点轨迹 |
| `poi_evidence_snapshot_id` | string/null | Redis 评分证据快照 ID；未配置快照 Store 时为空 |
| `poi_evidence_snapshot_sha256` | string/null | 快照规范化 JSON 内容摘要 |
| `poi_evidence_snapshot_record_count` | int | 快照内按 Provider、数据集和 POI ID 去重的记录数 |

### `SiteSelectionAnalysisCreate`

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| `project_type` | enum | 四种 Profile | 分析项目类型 |
| `analysis_scope` | enum | `market_selection` / `full_compliance` | Supervisor 根据用地证据自动设置；普通完整分析默认后者 |
| `candidate_parcels` | array | 至少 1 个、ID 唯一 | 手工输入或确认后的候选 |
| `poi_evidence_snapshot_id` | string/null | 仅安全 ID 字符 | 自动发现模式绑定的评分证据；手工模式为空 |

### `SiteSelectionSupervisorResponse`

| 字段 | 类型 | 含义 |
|---|---|---|
| `session_id` | string | Supervisor thread 业务标识，也是恢复 URL 参数 |
| `checkpoint_id` | string | 当前 LangGraph checkpoint 乐观并发版本 |
| `session_ttl_seconds` | int | Redis 租约剩余秒数 |
| `status` | enum | `running`、`awaiting_confirmation`、`awaiting_analysis`、`completed`、`failed`、`cancelled` 或 `timed_out` |
| `discovery_report` | object/null | 当前 session 冻结的候选发现报告 |
| `confirmation_request` | object/null | 等待确认时允许的候选 ID、快照 ID 和警告 |
| `confirmation` | object/null | 已选择候选、确认人、服务端确认时间和备注 |
| `analysis_run_id` | string/null | 与 Supervisor 关联的 Redis/RQ Run ID |
| `analysis_run_status` | enum/null | `queued/running/completed/failed/cancelled/timed_out` |
| `analysis_error_type` | string/null | 非成功终态的脱敏错误类型 |
| `analysis` | object/null | Supervisor 正式分析完成后的结构化结果 |
| `execution_plan`, `supervisor_trace` | object/array | 上层六节点 Plan 与执行轨迹 |

`SiteSelectionSupervisorConfirmRequest` 必须包含 `expected_checkpoint_id`、去重后的 `selected_candidate_ids` 和 `reviewer_id`。服务端生成 `confirmed_at`；客户端不能指定确认时间。当前 reviewer ID 为演示输入，尚未绑定认证主体。

### `SupervisorSessionEvent`

| 字段 | 类型 | 含义 |
|---|---|---|
| `event_type` | enum | started、awaiting_confirmation、confirmation_rejected、confirmed、analysis_submitted、analysis_completed/failed/cancelled/timed_out、completed |
| `occurred_at` | datetime | 服务端含时区 UTC 时间 |
| `checkpoint_id` | string | 事件发生时的图版本 |
| `analysis_run_id` | string/null | 触发提交或终态恢复的关联 Run |
| `reviewer_id` | string/null | 确认人演示标识 |
| `selected_candidate_ids` | array | 本次尝试涉及的候选 ID |
| `error_type` | string/null | 拒绝事件的脱敏异常类型，不保存异常正文 |

## 2. POI 契约

### `POIQuery`

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| `query_id` | string | 非空 | 查询标识 |
| `parcel_id` | string | 非空 | 所属候选地 |
| `group_key` | string | 非空 | Profile POI 分组 |
| `longitude`, `latitude` | float | 合法坐标范围 | WGS84 查询中心 |
| `categories` | array | 非空、去重 | 标准化类别 |
| `radius_m` | int | 100 到 50,000 | 查询半径，米 |
| `limit` | int | 1 到 1,000 | 最大返回数 |

### `POIRecord`

| 字段 | 类型 | 含义 |
|---|---|---|
| `poi_id` | string | Provider 前缀后的稳定标识 |
| `name` | string | 名称 |
| `category` | string | 标准化类别 |
| `longitude`, `latitude` | float | 标准化 WGS84 坐标 |
| `distance_m` | float/null | 相对本次查询中心的距离 |
| `attributes` | object | 源类别、源 CRS、地址等扩展属性 |

### `POISourceMeta`

`provider`、`dataset_id`、`dataset_version`、`dataset_updated_at`、`queried_at`、`crs`、`record_count` 组成最小来源链。`record_count` 表示实际返回数，`available_record_count` 表示应用查询上限前已确认的可用数，`dataset_record_count` 表示整个数据集总量；三者不得混用。`is_truncated` 必须严格等于 `available_record_count > record_count`。`is_synthetic` 与 `quality_notice` 明示数据性质和使用边界。发生降级时必须同时存在 `fallback_from` 和 `fallback_reason`。

候选发现与正式分析的证据关系使用以下字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `evidence_snapshot_id` | string/null | 本条证据关联的候选发现快照 |
| `evidence_reused` | boolean | 本条结果是否由快照本地裁剪；为真时必须有快照 ID |
| `evidence_supplemented` | boolean | 是否因快照不完整而执行候选点范围补查；不能与 `evidence_reused` 同时为真 |
| `evidence_supplement_reason` | string/null | `snapshot_truncated`、`snapshot_missing_group` 或 `snapshot_missing_categories` |
| `evidence_supplement_error` | string/null | 补查失败摘要；此时保留已有局部快照并保持不完整标记 |

普通 Provider 响应不带快照状态。成功补查保留原快照 ID，用于说明触发上下文，但 `evidence_reused=false`；缺组且补查失败时不会构造没有证据的来源对象，而是让正式分析失败关闭。新增字段都有默认值，旧 Run、旧 checkpoint 和旧来源 JSON 可继续读取。

### `CandidateDiscoveryPOISnapshot`

| 字段 | 类型 | 含义 |
|---|---|---|
| `snapshot_id` | string | Redis Key 的业务标识 |
| `discovery_request_id` | string | 生成快照的候选发现请求 |
| `project_type` | enum | 绑定的零售 Profile |
| `created_at` | datetime | 含时区的冻结时间 |
| `candidates` | array | 本次报告可确认的候选全集 |
| `feature_sets` | array | Profile 评分组的宽域 POI 证据，不含纯地图背景组 |
| `content_sha256` | string | 除摘要字段外规范化 JSON 的 SHA-256 |

模型禁止额外字段、重复候选和重复评分组，顶层为 frozen。提交正式分析时还会校验候选 ID、经纬度和 `geometry_dataset_id`。

## 3. 分析输出

| 对象 | 关键字段 | 说明 |
|---|---|---|
| `GISEvidence` | `status`, `dataset_ids`, `crs`, `geometry_valid`, `metrics`, `constraint_observations` | 空间来源、校验和数值证据 |
| `POIEvidence` | `status`, `feature_sets`, `soft_score`, `score_report` | POI 来源、指标和版本化软评分 |
| `PolicyEvidence` | `policy_ids`, `evaluated_rule_ids`, `rule_findings` | 已评估规则与命中结果 |
| `AnalysisResult` | `parcel_id`, 三类证据, `site_score_report`, `warnings` | 单候选地汇总，不生成自动合规结论 |
| `CandidateComparisonReport` | `scoring_version`, `candidates` | 候选地软评分排序与政策结果并列展示 |
| `EvidenceReviewReport` | `status`, `issues`, `requires_human_review` | 血缘完整性和人工复核要求 |
| `AgentExecutionPlan` | `plan_id`, `version`, `steps` | 闭合、无环、白名单化的 Agent/Skill DAG |
| `AgentSkillManifest` | `node_id`, `role`, `skill_name`, `skill_version`, `depends_on`, `parallel_group`, `llm_allowed`, `output_contract` | 单节点审核契约 |
| `AgentStepTrace` | `node_id`, `status`, `elapsed_ms`, `error_type` | 领域工作流的节点级执行轨迹 |
| `RunStageTrace` | `stage`, `status`, `elapsed_ms`, `error_type` | 清洗后的阶段可观测性 |
| `HumanReviewState` | `status`, `reason_codes`, `updated_at`, `note` | 已阅状态，不是审批状态 |

## 4. PostGIS Schema

Schema 名为 `site_selection`，当前迁移版本为 `002_retail_project_types`。

### `projects`

| 列 | PostgreSQL 类型 | 约束/索引 | 含义 |
|---|---|---|---|
| `project_id` | text | PK | 项目标识 |
| `project_type` | text | CHECK 四种 Profile | 项目类型 |
| `name` | text | 非空 | 项目名 |
| `created_at`, `updated_at` | timestamptz | 非空 | 审计时间 |

### `spatial_layers`

| 列 | 类型 | 约束/索引 | 含义 |
|---|---|---|---|
| `layer_id` | text | PK | 图层标识 |
| `project_id` | text | FK, B-tree | 所属项目 |
| `layer_type` | text | 非空 | 候选地或约束类型 |
| `source` | text | CHECK | `api` / `postgis` / `file` |
| `source_crs` | text | 非空 | 原始 CRS，保留真实语义 |
| `normalized_crs` | text | 固定 `EPSG:4326` | 入库几何 CRS |
| `version` | text | 非空 | 数据版本 |
| `data_hash` | char(64) | SHA-256 格式 | 稳定数据哈希 |
| `required_fields` | jsonb | array | 校验字段 |
| `metadata` | jsonb | object | Fixture、Profile 等元数据 |

### `spatial_features`

| 列 | 类型 | 约束/索引 | 含义 |
|---|---|---|---|
| `feature_id` | bigint | identity PK | 内部标识 |
| `layer_id` | text | FK, B-tree | 所属图层 |
| `source_feature_id` | text | 与 `layer_id` 唯一 | 源要素标识 |
| `geometry` | geometry(Geometry, 4326) | NOT NULL, GiST | 标准化几何 |
| `properties` | jsonb | object | 非几何属性 |

### `pois`

| 列 | 类型 | 约束/索引 | 含义 |
|---|---|---|---|
| `poi_id` | bigint | identity PK | 内部标识 |
| `source`, `source_id` | text | 联合唯一 | 去重键 |
| `name`, `category` | text | 非空；类别有 B-tree | 标准化名称与类别 |
| `source_crs` | text | 非空 | 源坐标语义，可为 `GCJ-02` |
| `normalized_crs` | text | 固定 `EPSG:4326` | 入库坐标系 |
| `geometry` | geometry(Point, 4326) | NOT NULL, GiST | WGS84 点 |
| `address` | text | 可空 | 地址 |
| `fetched_at` | timestamptz | 非空 | 获取时间 |
| `raw_payload` | jsonb | object | 经过边界控制的源数据 |
| `created_at`, `updated_at` | timestamptz | 非空 | 存储审计时间 |

## 5. Redis Keys

默认命名空间为 `site_selection`，Fixture Compose 使用 `site_selection:fixture`。

| Key 形式 | Value | TTL 用途 |
|---|---|---|
| `{ns}:run_state:{run_id}` | `RunState` JSON | 运行状态生命周期 |
| `{ns}:idempotency:{sha256(key)}` | run ID + 请求指纹 | 阻止重复运行和键冲突 |
| `{ns}:poi_cache:{sha256(query+scope)}` | `POIFeatureSet` JSON | POI 查询缓存 |
| `{ns}:discovery_snapshot:{snapshot_id}` | `CandidateDiscoveryPOISnapshot` JSON | 一次候选发现到确认之间的 POI 证据工作记忆，默认 7200 秒 |
| `{ns}:events:{run_id}` | `RunEvent` JSON list | 审计事件流 |
| `{ns}:supervisor:session:{session_id}` | 当前 checkpoint ID | Supervisor 可访问租约，默认 7200 秒 |
| `{ns}:supervisor:lock:{session_id}` | 随机锁 token | 确认临界区，默认 120 秒，必须短于 session TTL |
| `{ns}:supervisor:events:{session_id}` | `SupervisorSessionEvent` JSON list | 候选确认审计链，与 session 同窗口保留 |
| `{ns}:scenario_session:{session_id}` | `ScenarioConversationSession` JSON | 对话、待确认版本和已确认版本，默认 86400 秒 |

`RunState.status` 允许 `queued`、`running`、`completed`、`failed`、`cancelled`、`timed_out`。`failed` 和 `timed_out` 必须包含脱敏 `error`，其他状态禁止携带错误。异步运行的 `details.queue_job_id` 是确定性 RQ Job ID；`details.poi_evidence_snapshot_id` 记录提交 ID，`details.poi_evidence_snapshot_reused` 只有完成结果实际包含复用来源时才为真；凭据不进入 `details`。

RQ 自己维护 `rq:*` 队列、Job 和 Registry Key，其格式由 RQ 版本管理，不作为本项目领域存储契约。幂等与事件 TTL 不允许长于运行状态 TTL。Redis 密码只通过环境变量传入，不进入 Key、日志或响应。关键状态转换使用 Lua 比较并更新。

Supervisor checkpoint 表由官方 `langgraph-checkpoint-postgres` 的 `PostgresSaver.setup()` 管理，不由项目迁移脚本复制定义。项目代码只依赖公开 Checkpointer 契约，不直接查询或修改其内部表。Redis session 过期后访问会调用 `delete_thread()`；主动扫描孤立 checkpoint 的后台清理任务尚未实现。

## 6. 场景与对话对象

| 对象 | 关键字段 | 含义 |
|---|---|---|
| `ScenarioConstraintAction` | `operation`, `key`, `value`, `source_text` | LLM 或规则解析器提出的追加、覆盖、删除动作，不直接执行分析 |
| `ScenarioConstraint` | `key`, `value`, `readiness`, `reason` | 版本中累计保存的约束及其数据就绪状态 |
| `RegionResolution` | `normalized_name`, `center_*`, `discovery_bounds`, `source`, `provider`, `confidence`, `warnings` | 区域名称到候选发现窗口的可追溯转换 |
| `ScenarioVersion` | `version_id`, `parent_version_id`, `status`, `recorded_constraints`, `conflicts`, `clarifications`, `confirmed_by` | 不可变场景快照；只有 confirmed 版本可作为稳定下游输入 |
| `ScenarioConversationSession` | `messages`, `versions`, `active_version_id`, `pending_version_id` | Redis 中的可恢复会话聚合 |

`readiness=missing_data` 表示约束被记住但没有可信数据消费者，不能进入过滤或评分。`RegionResolution.discovery_bounds` 仍通过 `DiscoveryBounds` 校验；离线目录来源不代表权威行政区边界。原始消息不是长期事实，`active_version_id` 指向的 confirmed 版本才是当前执行记忆。

## 7. 评测结果

`evals/cases.json` 冻结输入和关键期望字段。`summary.json` 为每条案例记录 `case_id`、类别、场景、期望、实际、是否通过、耗时和异常类型。`performance.json` 记录样本数、预热次数、中位数、最小/最大耗时、运行状态和输入规模。
