# 选址 API、前置检查、结构化 Agent 与 Fixture POI

> 日期：2026-08-18
>
> 项目：建设项目选址与国土空间合规审查 Agent

## 一、本阶段目标

本阶段在已有确定性选址工作流上增加四层边界：

```text
HTTP API
-> 应用服务与运行时提供器
-> 前置检查与结构化 Agent 角色
-> 可替换的 POI 数据适配器
```

这些边界用于阻止不完整输入进入分析、隔离尚未审核的运行配置，并为后续接入真实 POI 数据源保留统一接口。

本阶段没有接入高德或 OSM，也没有新增真实政策规则、业务评分阈值或自动推荐结论。

## 二、应用服务与 API 边界

新增接口：

```text
POST /site-selection/preflight
POST /site-selection/analyses
```

`preflight` 接受尚未完整的项目草稿，返回 `ready / needs_input / unsupported`；`analyses` 只接受已经满足严格输入契约的分析请求。

请求 DTO 使用严格字段和枚举校验：

- 项目类型只能是 `shopping_mall` 或 `logistics_park`。
- 候选地块不能为空。
- 候选地块编号不能重复。
- 经纬度和面积继续复用领域模型约束。
- 未知字段和未知项目类型由 FastAPI/Pydantic 返回 `422`。

`SiteSelectionAnalysisService` 负责：

1. 将 API DTO 转换为 `ProjectRequest`。
2. 生成请求编号和带时区的请求时间。
3. 按项目类型解析 `SiteSelectionRuntime`。
4. 调用已有 `run_site_selection_workflow()`。

服务通过 `SiteSelectionRuntimeProvider` 获取数据清单、POI/GIS 网关、评分配置、空间约束和政策规则，不把这些环境配置写死在路由中。

默认提供器是 `UnconfiguredSiteSelectionRuntimeProvider`。在真实配置完成审核前，接口安全返回：

```text
503 runtime_unavailable
```

而不是使用合成规则或测试阈值生成看似真实的业务结果。

错误映射如下：

- 输入契约错误：`422`。
- 工作流证据或业务步骤阻断：`409 analysis_blocked`。
- 运行配置尚未就绪：`503 runtime_unavailable`。
- 未处理异常或不完整终态：清理原始异常内容后返回 `500 analysis_internal_error`。

成功响应要求状态为 `completed`、结果完整覆盖全部候选地块，并包含请求级候选对比报告。

## 三、严格请求之前的前置检查

`ProjectRequest` 适合已经完整、可以进入工作流的数据，但不能表达“项目类型尚未提供”这类补全阶段状态。因此新增：

```text
SiteSelectionDraft
-> evaluate_site_selection_draft()
-> PreflightDecision
```

`PreflightDecision.status` 只有三种状态：

- `ready`：项目类型受支持，候选地块和数据清单完整，可以进入严格请求创建。
- `needs_input`：返回明确的 `missing_fields`，不猜测缺失信息。
- `unsupported`：保留原始项目类型值，并停止后续分析。

当前补全检查覆盖：

- 项目类型。
- 候选地块列表。
- 每个候选地块的建设面积 `area_hectares`。
- 每个候选地块的 `geometry_dataset_id`。
- 数据清单。
- 候选地块引用但清单中不存在的数据集。

受支持的项目类型继续通过既有 `ProfileRegistry` 路由到商场或物流园 Profile，没有建立第二套 Profile 注册表。

该能力已经通过 `POST /site-selection/preflight` 暴露。未知项目类型不会先被严格枚举拒绝，而是返回结构化 `unsupported`；重复地块编号、重复数据集编号和字段类型错误仍由 API 契约返回 `422`。

## 四、四个结构化 Agent 角色

新增角色不是自由对话 Agent，而是对现有确定性业务能力的结构化封装。每个角色都有 Pydantic 输入和输出契约，并通过 `AgentRole` 标识职责。

### OrchestratorAgent

输入 `SiteSelectionDraft`，输出 `PreflightDecision`。它只负责路由和信息补全判断，不调用大模型，也不补造字段。

### SpatialAgent

输入 `AgentState`，依次复用：

```text
collect_gis_evidence()
-> run_gis_analysis()
-> run_spatial_constraint_analysis()
```

空间数据网关、约束配置和缓冲距离必须显式注入。任一候选地块的强制 GIS 证据未达到 `READY` 时抛出结构化阻断，不继续计算。

### PolicyAgent

输入 `AgentState` 和版本化 `RuleDefinition`，复用 `evaluate_policy_rules()` 生成政策证据。没有规则时在构造阶段拒绝启动。

### ReviewAgent

复用：

```text
assemble_analysis_results()
-> compare_candidate_results()
```

输出必须是 `completed`，必须完整覆盖全部候选地块，并包含候选对比报告。

四个角色没有复制 POI、GIS、规则或比较算法。以后是否由 LangGraph、API 服务或其他编排器调用，不改变底层业务契约。

## 五、POI 适配器接口

新增 `POISourceAdapter` 协议：

```python
def search(self, query: POIQuery) -> POIFeatureSet: ...
```

它与既有工作流使用的 POI Gateway 保持结构兼容。后续真实数据源只需实现同一查询和标准化输出契约，无需修改评分和工作流模块。

`POISourceMeta` 增加两个可选血缘字段：

- `dataset_version`
- `dataset_updated_at`

数据更新时间和查询时间都要求包含时区。

## 六、JSON Fixture POI

固定数据文件为：

```text
data/fixtures/poi.json
```

包含 32 条合成 POI，覆盖商场与物流园两个 Profile 中声明的全部 POI 类别。数据集记录：

- 数据集编号。
- Fixture 版本。
- `mock` provider。
- `EPSG:4326` 坐标系。
- 带时区的更新时间。
- 每条 POI 的编号、名称、类别、经纬度和合成数据标记。

`FixturePOIAdapter` 使用结构化 JSON 解析，并执行：

1. 类别过滤。
2. Haversine 距离计算。
3. 查询半径过滤。
4. 按距离和 POI 编号稳定排序。
5. 查询数量限制。
6. 复用既有指标计算函数生成 `POIFeatureSet`。

适配器要求至少 30 条记录、唯一 POI 编号、`mock` provider 和 `EPSG:4326`。原始 Fixture 不允许预置查询相关的 `distance_m`。

输入查询、数据集属性和返回记录均采用防御性复制，调用方修改返回结果不会污染后续查询。

## 七、运行时注册与应用注入

新增只读 `SiteSelectionRuntimeRegistry`，按 `ProjectType` 保存已经审核的运行配置。注册表具有以下约束：

- 注册键必须是受支持的项目类型。
- 注册键必须与 `SiteSelectionRuntime.project_type` 一致。
- 未配置的项目类型统一抛出 `SiteSelectionRuntimeUnavailableError`。
- 每次解析返回新的运行时快照，数据清单采用防御性复制。
- 应用服务会再次检查运行时项目类型与请求类型一致，错误配置不会进入工作流。

FastAPI 入口新增：

```python
create_app(runtime_provider=...)
```

部署环境可以在应用启动时显式注入审核后的注册表。没有传入提供器时仍使用 `UnconfiguredSiteSelectionRuntimeProvider`，保持默认关闭，不读取隐式演示配置。

## 八、测试覆盖

新增 18 项测试，覆盖：

- 商场和物流园正确路由。
- 未知项目类型返回 `unsupported`。
- 缺少项目类型、候选地块信息、建设面积和数据清单时返回 `needs_input`。
- 返回缺失的具体数据集引用。
- Orchestrator 结构化输出。
- GIS 数据缺失时 SpatialAgent 阻断。
- Agent 构造配置校验。
- Fixture 至少 30 条并覆盖两个 Profile 的类别集合。
- 类别、半径和数量限制。
- 空结果。
- 距离顺序稳定性。
- Provider、版本、CRS 和时间血缘。
- 查询结果与底层 Fixture 的防御性复制。
- 不支持的 Fixture 来源契约和无时区时间拒绝。

同时新增应用服务和 API 测试，覆盖成功、`422`、`409`、`500`、`503`、不完整完成状态、三态预检、运行时注册表和应用工厂注入。

此外增加显式 Fixture HTTP 端到端测试。测试运行时仅在测试代码中构造，实际经过：

```text
HTTP
-> Fixture POI
-> POI 评分
-> GIS 证据与指标
-> 空间约束
-> 合成测试规则
-> 结果组装
-> 候选对比
```

测试同时确认注册表只配置商场时，物流园分析仍返回 `503`。其中评分上下界和规则均带有 `fixture-test` 标识，不进入默认应用配置，也不代表真实业务判断。

最终验证结果：

```text
应用边界定向测试：38 passed, 1 existing warning
Fixture HTTP 端到端测试：2 passed, 1 existing warning
文件型空间 Gateway 定向组合：45 passed
PostGIS 与其他空间 Gateway 定向组合：61 passed
项目全量回归：269 passed, 1 existing warning
```

现有 warning 来自 FastAPI TestClient 与 Starlette/httpx 的第三方弃用提示，与本阶段业务改动无关。

## 九、当前边界与下一步

当前已经具备可测试的 API、前置检查、Agent 角色和离线 POI 数据边界，但默认 API 仍不会执行真实分析，因为正式运行配置尚未审核。

此外新增 `FileSpatialDatasetGateway`，可以从显式根目录读取 GeoJSON、JSON、GeoPackage 和 Shapefile。Manifest 必须使用 `DatasetSource.FILE` 和相对路径；绝对路径、目录穿越、根目录外的符号链接目标和不支持的格式会被拒绝。文件不存在映射为 `MISSING`，不安全或不可解析的文件映射为 `INVALID`，底层读取消息不会直接进入业务状态。

新增 `PostGISSpatialDatasetGateway`。数据库连接对象由应用启动层注入，Gateway 不读取或保存连接串。Manifest 的 `location` 只允许 `table` 或 `schema.table`，schema 必须在白名单中，schema、table 和几何列都必须匹配严格 SQL 标识符规则。查询只生成双引号包围的 `SELECT * FROM "schema"."table"`，拒绝分号、条件表达式、额外层级和未授权 schema。数据库异常只保留数据集编号与异常类型。

Compose 已使用 `postgresql+psycopg` URL，因此依赖清单增加 `sqlalchemy` 和 `psycopg[binary]`。

2026-08-19 已完成真实 PostGIS 实连验证：本地虚拟环境安装 `SQLAlchemy 2.0.52` 和 `psycopg 3.3.4`，Compose 中的 PostGIS 容器处于 healthy 状态。`scripts/smoke_postgis_gateway.py` 使用当前连接创建事务级临时空间表，通过 `PostGISSpatialDatasetGateway` 读取并执行空间数据校验，成功返回：

```text
PostGIS smoke OK: rows=1, crs=EPSG:32651, geometry=Polygon
```

临时表使用 `ON COMMIT DROP`，测试结束后不会留下持久业务表。随后执行项目全量回归，结果仍为 `269 passed, 1 existing warning`。

下一步应优先完成：

1. 明确真实数据清单、空间约束、政策规则和 POI 评分配置的来源与版本。
2. 为正式 PostGIS 数据集定义受审核的表清单、schema 白名单和只读连接权限。
3. 在有稳定网络和密钥管理方案后，再实现真实 POI Adapter。
4. 真实配置上线前继续保持默认应用关闭，并建立配置审核与发布流程。
