# 数据字典

## 1. 领域输入

### `ProjectRequest`

| 字段 | 类型 | 约束 | 含义 |
|---|---|---|---|
| `request_id` | string | 非空 | 单次分析请求标识 |
| `project_type` | enum | `shopping_mall` / `logistics_park` | Profile 路由键 |
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
| `required_fields` | array | 非空、去重 | 数据校验字段 |
| `updated_at` | datetime | 必须含时区 | 数据更新时间 |

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

`provider`、`dataset_id`、`dataset_version`、`dataset_updated_at`、`queried_at`、`crs`、`record_count` 组成最小来源链。发生降级时必须同时存在 `fallback_from` 和 `fallback_reason`。

## 3. 分析输出

| 对象 | 关键字段 | 说明 |
|---|---|---|
| `GISEvidence` | `status`, `dataset_ids`, `crs`, `geometry_valid`, `metrics`, `constraint_observations` | 空间来源、校验和数值证据 |
| `POIEvidence` | `status`, `feature_sets`, `soft_score`, `score_report` | POI 来源、指标和版本化软评分 |
| `PolicyEvidence` | `policy_ids`, `evaluated_rule_ids`, `rule_findings` | 已评估规则与命中结果 |
| `AnalysisResult` | `parcel_id`, 三类证据, `site_score_report`, `warnings` | 单候选地汇总，不生成自动合规结论 |
| `CandidateComparisonReport` | `scoring_version`, `candidates` | 候选地软评分排序与政策结果并列展示 |
| `EvidenceReviewReport` | `status`, `issues`, `requires_human_review` | 血缘完整性和人工复核要求 |
| `RunStageTrace` | `stage`, `status`, `elapsed_ms`, `error_type` | 清洗后的阶段可观测性 |
| `HumanReviewState` | `status`, `reason_codes`, `updated_at`, `note` | 已阅状态，不是审批状态 |

## 4. PostGIS Schema

Schema 名为 `site_selection`，迁移版本为 `001_initial`。

### `projects`

| 列 | PostgreSQL 类型 | 约束/索引 | 含义 |
|---|---|---|---|
| `project_id` | text | PK | 项目标识 |
| `project_type` | text | CHECK 两种 Profile | 项目类型 |
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
| `{ns}:events:{run_id}` | `RunEvent` JSON list | 审计事件流 |

`RunState.status` 允许 `queued`、`running`、`completed`、`failed`、`cancelled`、`timed_out`。`failed` 和 `timed_out` 必须包含脱敏 `error`，其他状态禁止携带错误。异步运行的 `details.queue_job_id` 是确定性 RQ Job ID；凭据不进入 `details`。

RQ 自己维护 `rq:*` 队列、Job 和 Registry Key，其格式由 RQ 版本管理，不作为本项目领域存储契约。幂等与事件 TTL 不允许长于运行状态 TTL。Redis 密码只通过环境变量传入，不进入 Key、日志或响应。关键状态转换使用 Lua 比较并更新。

## 6. 评测结果

`evals/day26_cases.json` 冻结输入和关键期望字段。`day26-summary.json` 为每条案例记录 `case_id`、类别、场景、期望、实际、是否通过、耗时和异常类型。`day26-performance.json` 记录样本数、预热次数、中位数、最小/最大耗时、运行状态和输入规模。
