# 候选位置自动发现

候选自动发现面向咖啡店和便利店。系统优先从已经登记了地块几何和用地属性的机会单元池中筛选；资料不足时可以降级到商业用地代理或纯市场探索。所有三级结果都可进入商业选址分析，但只有完整用地机会单元可以执行 GIS、政策规则和用地合规审查。

## 三级发现策略

| 策略 | 输入数据 | 输出 | 商业选址分析 | 用地合规审查 |
|---|---|---|---|---|
| `registered_land` | `parcel_id`、Polygon、面积、用地类别、适配状态 | 可审计候选地块 | 可以 | 可以，仍可能要求人工复核 |
| `commercial_land_proxy` | 现状商业/商住混合用地 Polygon | 商业用地代理候选 | 可以 | 不可以，必须补充权威用地核验 |
| `market_exploration` | 范围与 POI 市场证据 | 市场机会网格 | 可以 | 不可以，状态为待核验 |

默认 `fallback_mode=market_exploration`，顺序尝试登记用地、商业用地代理、市场网格。`commercial_land_proxy` 最多降级到商业用地；`strict` 缺少完整机会单元时直接阻断。

## 工作流

```text
范围与业态输入
      |
      v
发现范围校验
      |
      +-----------------------+
      |                       |
      v                       v
用地适配硬门禁          范围级 POI 市场证据
      |                       |
      +-----------+-----------+
                  v
      不完整评分组 2x2 分区补查
                  |
                  v
          评分、排序与空间去重
                  |
                  v
          人工确认候选位置
                  |
                  v
       按证据范围路由分析工作流
          /                 \
  POI 商业选址分析       GIS、规则与合规审查
```

`land_use_gate` 和 `poi_market_evidence` 是无依赖并行节点。用地门禁是硬约束，POI 评分是软排序证据；再高的市场分也不能覆盖被排除的用地状态。

五个节点由 `build_candidate_discovery_execution_plan()` 定义，并通过通用 `compile_agent_plan_graph()` 编译为真实 LangGraph。`CandidateDiscoveryGraphState` 为用地结果、POI 结果和各节点 Trace 设置独立字段，避免并行写冲突；`rank_diversify` 使用双依赖 fan-in，只在两类证据都结束后执行一次。编译器会拒绝缺失 Handler 或计划外隐藏节点，因此接口返回的执行计划、节点 Trace 和实际运行拓扑是一张图。`CandidateDiscoveryService` 只是同步应用入口，不再手工创建用地/POI 业务线程池。

## 用地门禁

每个机会单元必须有稳定的 `parcel_id`、Polygon 几何、面积、用地类别和适配状态。状态只有三种：

- `allowed`：可进入排序，但不等于已经取得许可。
- `review_required`：可进入排序，结果必须显式标记人工核验。
- `excluded`：在评分前剔除，不能成为候选。

缺失机会单元图层、字段、CRS、有效几何或适配状态时，系统不会用 POI 分数猜测用地合法性。允许降级时返回 `formal_analysis_allowed=false`，其含义是“不能给出用地合规判断”，不再表示“禁止全部分析”。零售 Supervisor 会自动选择 `market_selection`，继续完成 POI、交通、需求代理、竞品评分和候选对比；严格模式仍直接关闭发现失败。

商业用地代理要求图层至少包含 `parcel_id` 和 `land_use`，并具有有效的投影坐标 Polygon。系统只接受商业、零售、商住混合、商务等可识别类别，其他类别在代理生成阶段排除。代理候选统一为 `review_required`。

## POI 查询与评分

系统根据 Provider 能力选择查询计划。本地 Fixture 可以在一次响应中完整区分多个类别，因此离线测试可把评分类别合并成一个范围级查询、其余类别合并成一个背景查询。高德和公共 Overpass 都可能被超大范围、多类别查询拖慢，因此在线模式按 Profile 的六个评分组查询，背景类别最多三类一批，并发执行后再按矩形边界去重合并。

首轮评分证据出现在线降级、返回截断或缺少 Profile 必需类别时，`poi_market_evidence` 会在加载范围背景类别之前执行有界 2x2 分区补查。每个分区查询覆盖本分区及评分服务半径，最多为一个受影响评分组增加 4 个查询；只合并真实在线结果，并按 Provider 与 POI ID 去重。四个分区全部成功、均未截断且类别齐全时才恢复为完整证据；部分失败、再次降级或仍缺类别时继续标记不完整。补查覆盖整个发现范围而不是只覆盖首轮前几名候选，因此不会产生“先入选者优先获得更多证据”的排序偏差。

修复后的评分证据用于第一次排名、范围地图和 Redis 证据快照。它与确认后的候选点按需补采分工不同：发现阶段分区补查用于公平修复候选池，候选分析阶段补采用于按候选中心和 Profile 半径形成局部证据。市场选址与完整合规两条分支都复用同一个 Gateway、Redis 查询缓存、限速、熔断、PostGIS 持久化和显式 Fixture 降级。

高德单个批次默认最多翻 2 页，每页最多 25 条；候选发现的上游请求速率默认 2 次/秒。页数预算用于限制冷启动延迟，不会把截断结果伪装成完整数据：Provider 报告的可用数量大于返回数量时，`is_truncated=true`，界面继续展示“存在返回上限”。相同中心、半径、类别和上限的查询由 Redis 缓存 1 小时，第二次执行会在来源表中标记 `cache_hit=true`。

POI 分为两条数据通道：

- 评分证据：只包含当前业态 Profile 定义的类别，参与候选软评分。
- 范围背景层：补查所有已审核支持的 30 类 POI，严格裁剪到用户选择的矩形范围，按 Provider 与 POI ID 去重，仅用于地图观察和数据覆盖核验。

范围背景层不会改变评分。响应通过 `range_pois` 返回记录，通过 `range_poi_observed_count` 表示去重后观察到的数量；`range_poi_is_truncated=true` 表示 Provider 或响应上限导致记录可能不完整。所谓“全部”仅限当前 Provider 已收录、当前支持类别和 API 返回上限内，不能宣称覆盖现实世界的所有设施。

咖啡店和便利店分别使用自己的权重与指标方向。竞争对手数量越少越优、最近竞争对手距离越远越优；交通、办公、居住、学校和互补业态使用对应的便利度或需求代理指标。

POI 只能表达设施分布和潜在需求代理信号，不能被描述为真实客流。要形成生产级商业结论，还需接入匿名化客流、消费、租金、人口栅格和道路可达性等经授权数据。

## 发现与候选分析共用证据

候选发现完成排序后，会把六个评分组的宽域 `POIFeatureSet`、返回候选、项目类型、创建时间和内容 SHA-256 保存为 Redis `CandidateDiscoveryPOISnapshot`。响应只把快照 ID、摘要和去重记录数返回 Workbench，不把上千条评分 POI 塞进下一次 HTTP/RQ 载荷。

用户确认候选时，Workbench 将 `poi_evidence_snapshot_id` 与所选候选一并提交。API/Worker 依次校验：

- 快照存在且 TTL 未过期；
- 项目类型与发现请求一致；
- 每个候选 ID 属于快照；
- 经纬度和 `geometry_dataset_id` 没有被替换。

候选分析仍按每个候选和每个 Profile 组生成独立 `POIQuery`。`SnapshotReusingPOIGateway` 先检查对应宽域评分组：类别齐全且未截断时，从快照本地按类别、候选中心、半径和 limit 裁剪并重算距离与指标；快照被 Provider 截断、缺组或缺类别时，只对受影响候选执行同一条查询。这样不会减少六个评分组，也不会把全区域查询上限造成的边缘稀疏误判成真实市场空白。

候选点补查继续使用运行时 Gateway，因此已有的 Redis 查询缓存、Provider 限速、重试/熔断、PostGIS 持久化和 Fixture 显式降级仍然生效。补查成功时来源写入 `evidence_snapshot_id`、`evidence_supplemented=true` 和原因，不冒充快照复用；补查失败但宽域快照仍有部分记录时，系统保留局部快照、维持 `is_truncated=true` 并记录失败原因。评分组完全缺失且补查失败时没有可用证据，正式分析关闭失败。

默认 `SITE_SELECTION_DISCOVERY_SNAPSHOT_TTL_SECONDS=7200`。快照缺失、过期或候选错配时返回 `409 analysis_blocked`，不会静默改用另一批在线或 Fixture 数据。Profile 后续新增、旧快照确实缺少的评分组可以走当前 Provider，避免配置演进后完全无法执行。

## 空间去重与人工边界

候选按市场分排序后执行最小距离约束，避免返回多个实际属于同一商圈的相邻点。发现接口始终返回 `confirmation_required=true`。登记用地结果显示“确认候选并运行完整分析”；商业代理和市场探索结果显示“确认候选并运行商业选址分析”。后者不再禁用，但其 GIS 与政策节点记录为 `skipped`，结果中的用地合规状态固定为待核验。

## Supervisor 可恢复确认

领域层通过 `SiteSelectionSupervisor` 把候选发现、人工确认和异步正式分析组合为六节点图。发现完成后，`candidate_confirmation` 使用 LangGraph `interrupt()` 等待人；合法选择触发 `analysis_submitted` 幂等创建 RQ Run，随后 `analysis_wait` 使用第二个 interrupt 等待 Worker 终态。queued 不会被误报为 completed。

恢复入口在执行 `Command(resume=...)` 前校验候选白名单和分析范围。报告外候选、重复 ID 或非零售的无用地候选都会被拒绝；非法输入不会消费原 interrupt。Submitter 根据 `formal_analysis_allowed` 自动选择 `full_compliance` 或 `market_selection`，并强制带入发现报告的 `poi_evidence_snapshot_id`，因此两条分支都复用同一批证据，而不是重新联网发现。

当前 Compose API 与 Worker 都启用官方 PostgresSaver，Redis 负责 session TTL、通用状态转换锁、RunState 和审计事件；Workbench 把 session ID 写入 URL 并每 2 秒自动恢复状态。确认请求必须带页面看到的 checkpoint ID，陈旧页面或并发确认返回 409；候选表只允许勾选，冻结的几何由服务端 checkpoint 恢复。

单元测试仍使用 `InMemorySaver`；Compose 使用官方 PostgresSaver。上一阶段真实 Docker 已安装 `langgraph-checkpoint-postgres 3.1.2` 并验证 API 重启恢复。本轮代码新增 Worker 终态恢复、GET 幂等对账以及七段成功审计契约；覆盖主仓库并重建容器后需再跑真实 Smoke。租户隔离、认证身份、后台物理清理和多 API 竞争仍待实现。

## Fixture 边界

演示环境为咖啡店和便利店各提供 25 个合成机会单元，覆盖 `allowed`、`review_required`、`excluded` 三种状态。它们用于验证工作流与证据链，不代表真实规划许可、城市覆盖率、商业活力或客流。

Workbench 不会在首次打开时自动套用这批机会单元，也不会把用户输入的行政区悄悄替换成 Fixture 范围。任意区域没有已登记机会单元时继续返回 `market_exploration` 和 `formal_analysis_allowed=false`，但仍可完成商业选址分析。演示用地入口降为“演示与开发选项”，只有用户明确选择时才会：

- 从 `FixtureCandidateCatalog` 的零售候选中心计算带边距的演示范围；
- 把 `fallback_mode` 固定为 `strict`，禁止再次降级为商业代理或市场网格；
- 创建新的 Supervisor session，不改写当前历史 session；
- 在结果区展示 `demo-*-discovery-pool` 数据集 ID 和合成用地警告；
- 允许通过用地门禁的候选进入人工确认和正式分析，但不把演示结果解释为真实许可。

当前咖啡店演示范围约为 `121.295–121.365 / 31.145–31.185`，便利店约为 `121.295–121.365 / 31.315–31.355`。这些值由版本化目录计算，不是页面默认区域或现实行政边界。Fixture 目录变更时测试会重新验证推导范围。

生产环境优先使用经过治理的地籍、规划用途、建筑 AOI 或房源空间数据，并记录来源、更新时间、许可证或规划用途版本。当前已增加两条接入路径：`OverpassLandUseProvider` 自动查询 OSM 商业/零售用地与商业建筑多边形，证据等级为 `public_observation`；`import_authoritative_land_use.py` 将主管部门或内部授权的标准化空间文件写入 PostGIS，只有显式声明来源、许可、米制分析 CRS 和 `authoritative` 元数据后才可配置为权威 Manifest。OSM 能替代任意网格改善市场候选，但不能替代法定核验。在线用地失败时，strict 模式关闭失败；其他模式保留既有代理或市场降级并展示原因。

Docker Compose 默认使用 `SITE_SELECTION_POI_PROVIDER=auto`。有 `AMAP_API_KEY` 时优先高德，否则使用 Overpass；网络、限流或上游故障时按配置降级到 Fixture。Workbench 会分别展示搜索边界内 POI、边界内真实在线 POI、评分缓冲区快照 POI 和 Fixture 降级批次；正式分析来源表还披露快照复用、候选点补查、触发原因和失败原因。评分缓冲区为边缘候选的服务半径提供证据，可能超出原始搜索边界，因此快照数量不应与地图点数直接比较。

交互式候选发现采用有界快速降级默认值：单次在线请求最多等待 8 秒、默认不在同步请求内重试、连续 6 个查询批次发生可用性失败才打开 30 秒熔断。原阈值 1 会让某个评分组的偶发失败立即阻断其他五组和补查请求，造成系统性类别稀疏；阈值 6 允许一个完整评分轮次独立探测，同时仍由 2 次/秒限速、固定 2x2 网格和熔断控制上界。所有不完整评分组的分区查询进入同一个最多 4 Worker 的交错队列，不再逐组串行等待；Worker 只并行等待响应，Gateway 的共享限速器仍约束实际发出速率。显式把 `SITE_SELECTION_POI_FAILURE_THRESHOLD` 配为 1 仍保留快速失败模式。降级结果不会写入在线 Redis 缓存，后续发现可在熔断恢复后探测上游。高德和 Overpass 默认最多每批 3 个类别。可在 `.env` 调整 `SITE_SELECTION_POI_TIMEOUT_SECONDS`、`SITE_SELECTION_POI_MAX_ATTEMPTS`、`SITE_SELECTION_POI_FAILURE_THRESHOLD`、`SITE_SELECTION_POI_REQUESTS_PER_SECOND`、`SITE_SELECTION_AMAP_MAX_PAGES_PER_SEARCH`、`SITE_SELECTION_AMAP_MAX_CATEGORIES_PER_QUERY` 和 `SITE_SELECTION_OVERPASS_MAX_CATEGORIES_PER_QUERY`。宿主机代理应通过 `SITE_SELECTION_POI_PROXY_URL=http://host.docker.internal:7897` 显式传入容器。提高页数、失败阈值或类别预算会增加恢复机会，也会提高请求量、响应体和冷启动时间。

Supervisor 启动仍是同步完成候选发现后返回人工确认点。Workbench 普通 API 默认超时保持 90 秒，只有 `POST /site-selection/supervisor/sessions` 使用至少 150 秒的有界超时，覆盖首次公网冷查询的尾部延迟。该超时只是 UI 保护；主要性能修复是全局 4 Worker 交错调度。页面会提示首次在线分区补查可能需要几十秒，超时错误会明确指出补查尚未完成以及已完成缓存可被后续新任务复用。

## 接口

```http
POST /site-selection/candidates/discover
```

请求包含 `project_type`、WGS84 边界、候选数量、最小间距和 `fallback_mode`。当前只接受 `coffee_shop` 与 `convenience_store`，范围对角线最大 20 公里。响应包含 `strategy`（新增 `public_land_observation`）、`land_evidence_level`、用地来源 URI、许可、缓存命中、`formal_analysis_allowed`、候选、市场评分、用地状态、警告、执行计划、节点轨迹、`poi_evidence_snapshot_id/sha256/record_count`，以及分区补查组数、查询数、成功数、新增记录数和仍不完整评分组。每个评分来源同时披露 `evidence_complete`、`incomplete_reasons`、`repair_attempted`、`repair_query_count`、`repair_success_count` 和 `repair_added_record_count`。
