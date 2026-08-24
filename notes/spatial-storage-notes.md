# 空间校验、PostGIS 持久化与 Redis 运行状态说明

## 1. 本批目标与结论

本批在既有 `practice/site_selection` 架构中补齐空间数据进入数据库前的质量门、可审计哈希、PostGIS 最小持久化层、POI 标准化与去重，以及 Redis 运行状态存储。

最终验收结果：

- 缺少 CRS、空几何、无效几何和非米制投影坐标系均会被结构化阻断；
- 相同空间数据得到稳定 SHA-256 哈希，行顺序和索引变化不影响结果；
- PostGIS 已建立项目、空间图层、空间要素和 POI 四张业务表；
- 空间字段固定声明 SRID 4326，并建立 GIST 空间索引；
- POI 按 `source + source_id` 去重，重复写入更新原记录；
- Redis 状态键使用命名空间，JSON 内容经过模型校验，并具有显式 TTL；
- 真实 PostGIS、Redis 冒烟测试均通过；
- 项目全量回归为 `296 passed, 1 existing warning`。

本批没有引入真实高德或 OSM 接口，没有新增生产评分阈值、政策规则或自动推荐结论。

## 2. CRS、投影和 SRID 基础

### 2.1 地理坐标系

地理坐标系使用经度和纬度描述地球表面位置。WGS84 常见数据库表示是 `EPSG:4326`。它的坐标单位是角度，不是米。

经纬度不能直接用于平面面积和距离计算，原因包括：

- 一度经度代表的实际距离随纬度变化；
- 经纬度描述椭球表面，不是等距平面；
- 直接对经纬度多边形调用平面面积会得到“平方度”，不是平方米；
- 在不同地区使用固定角度阈值会产生不同的实际距离。

### 2.2 投影坐标系

投影坐标系把地球表面映射到平面。执行地块面积、缓冲区和工程距离分析时，应选择适合项目区域且线性单位为米的投影坐标系。

`validate_spatial_dataset()` 默认要求：

1. CRS 可解析；
2. CRS 是投影坐标系；
3. 投影轴单位是 metre/meter，换算因子为 1；
4. 数据字段和几何完整有效。

数据库统一使用 `EPSG:4326` 存储，主要用于交换、索引和跨数据源统一。真正的面积和工程距离分析仍应在适合当地的米制投影中完成，或者明确使用 PostGIS `geography` 语义。

### 2.3 SRID

SRID 是数据库空间字段声明的坐标参考标识。迁移中使用：

```sql
geometry geometry(Geometry, 4326) NOT NULL
geometry geometry(Point, 4326) NOT NULL
```

这不仅记录“坐标长得像经纬度”，还约束数据库中的几何必须带 SRID 4326。Repository 写入前会把空间图层重投影到 `EPSG:4326`。

### 2.4 GCJ-02 边界

GCJ-02 不是 EPSG:4326。`POINormalizer` 对 GCJ-02 输入直接抛出 `UnsupportedPOICRSError`，避免把偏移坐标伪装成 WGS84。

当前固定数据统一使用 WGS84。未来接入高德时必须增加经过验证的真实坐标转换环节，同时保留原始 `source_crs`。

## 3. 总体调用链

```text
GeoDataFrame
    -> validate_spatial_dataset()
    -> stable_spatial_hash()
    -> PostgresSpatialRepository.replace_layer()
    -> 重投影为 EPSG:4326
    -> spatial_layers + spatial_features

RawPOI
    -> POINormalizer.normalize()/normalize_many()
    -> NormalizedPOI
    -> PostgresPOIRepository.upsert_many()
    -> pois，按 source + source_id 去重

业务运行事件
    -> RedisRunStateStore.update()
    -> RunState JSON
    -> namespace:run_id，写入时设置 TTL
```

Repository 不自行读取 `.env`，不自行创建数据库连接，也不自行提交事务。调用方负责注入 SQLAlchemy Connection 或 Redis Client，并决定事务边界。这使单元测试可以使用 fake，同时让应用层掌握提交和回滚。

## 4. 文件与职责

### 4.1 空间校验与哈希

#### `practice/site_selection/spatial/validate.py`

核心类型：

- `SpatialValidationCode`：稳定的错误代码枚举；
- `SpatialValidationError`：包含 `code`、问题行索引和缺失字段；
- `SpatialValidationResult`：成功校验后的可序列化审计摘要；
- `parse_crs()`：通过 PyProj 解析 CRS；
- `validate_spatial_dataset()`：执行完整质量门；
- `_linear_unit_name()`、`_uses_metre()`：读取并验证投影轴单位。

质量门顺序：

1. 输入必须是 `GeoDataFrame`；
2. 数据集不能为空；
3. 必须有活动 geometry 列；
4. 必需业务字段必须齐全；
5. CRS 必须存在且可解析；
6. 如声明 `expected_crs`，实际 CRS 必须一致；
7. 需要度量分析时必须是米制投影；
8. 几何不能为 null；
9. 几何不能为空；
10. 几何拓扑必须有效。

校验函数只读输入，不会静默修复、重投影或修改原始数据。调用方必须明确决定如何处理错误数据。

#### `practice/site_selection/spatial/hashing.py`

`stable_spatial_hash()` 生成 64 位十六进制 SHA-256：

- 先复用空间质量门；
- 对几何执行 Shapely normalize；
- 使用固定维度、字节序和 WKB 表达；
- 属性列按名称排序；
- 每行转换为确定性 JSON；
- 所有行再次排序，因此行顺序和 DataFrame 索引不影响结果；
- CRS、属性列和算法版本均参与哈希。

哈希用于数据血缘和变更检测，不用于安全签名。属性出现 NaN 或无穷值时会被拒绝，避免不稳定序列化。

### 4.2 POI 标准化

#### `practice/site_selection/poi_normalizer.py`

核心类型：

- `RawPOI`：数据源原始记录；
- `NormalizedPOI`：可以进入统一存储的 WGS84 记录；
- `UnsupportedPOICRSError`：无法可靠转换的坐标系错误；
- `POINormalizer`：来源、类别、地址和坐标系标准化服务。

关键规则：

- `source` 去除首尾空格并转为小写；
- 类别通过显式 `category_aliases` 映射，不做模糊猜测；
- 地址去除首尾空格；
- `fetched_at` 必须包含时区；
- `identity_key` 固定为 `(source, source_id)`；
- 只接受 WGS84/EPSG:4326；
- GCJ-02 和未知坐标系均被阻断。

调用示例：

```python
raw = RawPOI(
    source="fixture",
    source_id="poi-001",
    name="示例站点",
    category="bus_stop",
    longitude=121.4705,
    latitude=31.2305,
    source_crs="WGS84",
    fetched_at=fetched_at,
)
normalized = POINormalizer({"bus_stop": "公交站"}).normalize(raw)
```

### 4.3 PostGIS Schema

#### `deploy/init_postgis.sql`

Compose 首次创建数据库时的入口脚本，负责引入版本化迁移。

#### `deploy/migrations/001_initial.sql`

迁移使用事务包裹，并以 `schema_migrations` 记录版本。核心表如下。

| 表 | 作用 | 核心约束 |
|---|---|---|
| `projects` | 项目主记录 | 项目类型只允许商场和物流园 |
| `spatial_layers` | 图层元数据和血缘 | CRS、版本、哈希、必需字段、更新时间 |
| `spatial_features` | 图层内空间要素 | `(layer_id, source_feature_id)` 唯一 |
| `pois` | 标准化 POI | `(source, source_id)` 唯一 |

空间索引：

- `spatial_features_geometry_gix`；
- `pois_geometry_gix`。

普通辅助索引：

- 图层项目 ID；
- 要素图层 ID；
- POI 类别。

`ON DELETE CASCADE` 保证删除项目时清理所属图层，删除图层时清理所属要素。

### 4.4 PostGIS Repository

#### `practice/site_selection/storage/postgres.py`

数据模型：

- `ProjectStorageRecord`：项目存储模型；
- `SpatialLayerWrite`：写入图层时的请求模型；
- `StoredSpatialLayer`：数据库图层记录，增加源 CRS、标准 CRS 和哈希；
- `StoredSpatialFeature`：数据库空间要素返回模型；
- `SQLConnection`：最小连接协议，便于注入 SQLAlchemy Connection 或测试 fake。

`PostgresSpatialRepository` 方法：

- `upsert_project()`：按 `project_id` 新增或更新项目；
- `get_project()`：按 ID 读取项目；
- `replace_layer()`：校验、哈希、重投影并整体替换图层要素；
- `get_layer()`：按 ID 读取图层元数据；
- `get_feature()`：按图层 ID 和源要素 ID 读取单个要素。

`replace_layer()` 的实现顺序非常重要：

1. 校验 GeoDataFrame、必需字段和源要素 ID 字段；
2. 保存源 CRS；
3. 计算稳定数据哈希；
4. upsert 图层元数据；
5. 删除该图层旧要素；
6. 重投影到 EPSG:4326；
7. 使用参数列表批量写入新要素。

应在调用方事务中执行该方法。若中途失败，调用方回滚后旧图层仍然存在，不会留下半替换状态。

所有业务值均通过 SQLAlchemy 绑定参数传递。表名和列名固定在代码中，没有把用户输入拼入 SQL。

#### `practice/site_selection/storage/poi_repository.py`

数据模型：

- `StoredPOI`：标准化 POI 加数据库 ID 和创建/更新时间；
- `NearbyPOI`：增加距离米数。

`PostgresPOIRepository` 方法：

- `upsert_many()`：先在内存按 identity key 去重，再执行数据库 upsert；
- `get()`：按 `source + source_id` 读取；
- `search_nearby()`：按中心点、米制半径、可选类别和 limit 查询。

附近查询把 EPSG:4326 geometry 转为 geography，再调用 `ST_DWithin` 和 `ST_Distance`。因此 `radius_m` 和返回的 `distance_m` 都是米，而不是经纬度角度。

数据库唯一约束是最终一致性防线。即使多个进程同时写入相同 POI，也不会生成重复记录。

### 4.5 Redis 运行状态

#### `practice/site_selection/storage/redis_state.py`

核心类型：

- `RunStatus`：`queued/running/completed/failed`；
- `RunState`：运行 ID、状态、更新时间、错误和扩展详情；
- `RedisClient`：最小客户端协议；
- `RedisRunStateStore`：命名空间 JSON 状态存储。

状态约束：

- `failed` 必须带错误信息；
- 非 `failed` 状态不能带错误信息；
- `updated_at` 必须带时区；
- namespace 和 run ID 只允许安全字符；
- TTL 必须大于零。

键格式：

```text
site_selection:run_state:<run_id>
```

默认 TTL 是 86400 秒。每次 `save()`/`update()` 都通过 Redis `SET ... EX` 同时写值和过期时间，避免写入后遗漏 TTL。

主要方法：

- `save()`：保存已经构造好的 `RunState`；
- `get()`：读取并重新执行模型校验；
- `update()`：创建带 UTC 时间的状态并保存；
- `delete()`：删除运行状态；
- `ttl()`：读取剩余生存时间。

Redis 仅保存短期运行状态，不代替 PostGIS 中的长期业务数据或审计记录。

## 5. 脚本与运行方式

### 5.1 应用迁移

```powershell
python .\scripts\apply_postgis_migrations.py
```

脚本从项目根目录 `.env` 读取连接参数，通过 SQLAlchemy 创建数据库连接，然后执行 `001_initial.sql`。成功输出：

```text
PostGIS migration OK: version=001_initial
```

### 5.2 真实 PostGIS 冒烟测试

```powershell
python .\scripts\smoke_storage_repositories.py
```

该脚本真实验证：

- 项目 upsert 和读取；
- 图层哈希、重投影和要素写入；
- 图层和要素回读；
- POI 重复写入更新；
- 按米制半径查询附近 POI；
- 参数化清理测试数据。

已验证输出：

```text
Storage smoke OK: project=storage-smoke-project, layer_hash=ce203b93a019, features=1, pois=1, deduplicated=true
```

### 5.3 真实 Redis 冒烟测试

```powershell
python .\scripts\smoke_redis_state.py
```

该脚本验证连接、PING、写入、回读、TTL，并在结束时删除测试键。已验证输出：

```text
Redis state smoke OK: namespace=site_selection:smoke, ttl=300
```

## 6. 测试覆盖

新增 39 项定向测试：

- 空间校验：CRS、米制单位、必需字段、null/empty/invalid geometry、输入不变性；
- 空间哈希：重复稳定、行序无关、等价几何归一、属性变化和非有限数值；
- POI 标准化：来源、类别、地址、时区、GCJ-02 和未知 CRS；
- PostGIS Repository：参数绑定、项目读取、图层替换、重投影、批量写入和要素读取；
- POI Repository：去重、按标识读取、附近查询参数化及参数边界；
- Redis：namespace、TTL、状态一致性、非法键和删除；
- 迁移：业务表、SRID、GIST 索引和 POI 唯一约束。

验证记录：

```text
定向测试：39 passed
全量回归：296 passed, 1 warning
PostGIS migration：version=001_initial
PostGIS storage smoke：passed
Redis state smoke：passed
```

唯一 warning 是既有 FastAPI/Starlette TestClient 对 httpx 的弃用提示，与本批存储功能无关。

## 7. 安全与事务边界

- SQL 业务值均使用绑定参数；
- Repository 不接收任意表名或 SQL 片段；
- 数据库密码和 Redis 密码只从环境变量读取，不写入代码；
- 迁移失败会回滚；
- Repository 不擅自 commit，应用层负责原子事务；
- Redis 键限制字符集，避免命名空间污染；
- 冒烟脚本只使用固定测试 ID，并清理自己的测试记录；
- 生产数据库账号仍应按最小权限原则单独配置。

## 8. 当前限制与后续工作

当前实现是最小可靠数据层，还没有完成：

- Alembic 等增量迁移框架；
- Repository 与 FastAPI/LangGraph 运行时的正式依赖注入；
- 项目级完整审计事件表；
- Redis 状态转换图和并发版本控制；
- 高德 GCJ-02 到 WGS84 的真实转换；
- OSM/高德在线 POI Adapter；
- 大批量 COPY、分页和数据库性能基准；
- 生产备份、恢复、监控和密钥管理。

建议下一阶段优先把 Repository 注入应用服务，明确一次分析运行的事务和状态转换，再接在线数据源。不要在真实阈值和政策规则未经审核前生成“推荐”或“合规通过”结论。
