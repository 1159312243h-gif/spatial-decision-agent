# 空间数据 CRS 与几何有效性校验

> 目标：不合法的空间数据不能进入距离、面积、缓冲区或叠加分析

## 一、为什么需要空间数据闸门

普通 Pydantic 模型可以校验字符串、数值、枚举和字段结构，但无法独立判断 GeoDataFrame 的 CRS 和几何拓扑是否合法。

空间分析前必须增加确定性校验：

```text
GeoDataFrame
  -> 数据集非空
  -> 活动 geometry 列存在
  -> 业务必需字段齐全
  -> CRS 存在且可解析
  -> 米制分析必须使用投影坐标系
  -> 不含 None 几何
  -> 不含 EMPTY 几何
  -> 几何拓扑有效
  -> 允许进入 GIS 分析
```

这些步骤属于固定安全边界，不应交给 LLM 自由决定是否执行。

## 二、CRS 是什么

CRS 全称是 Coordinate Reference System，中文通常称为坐标参考系统。

它回答两个关键问题：

- 坐标数字表示地球上的哪个位置？
- 坐标单位是角度还是米等线性单位？

例如：

- `EPSG:4326` 是地理坐标系，单位主要是度。
- `EPSG:32651` 是 WGS 84 / UTM 51N 投影坐标系，单位是米。

没有 CRS 时，一组 `(121.47, 31.23)` 或 `(300000, 3450000)` 只是数字，程序无法可靠解释其空间意义。

## 三、地理坐标系与投影坐标系

地理坐标系使用经纬度，适合存储和交换全球位置。投影坐标系把地球表面转换到平面，适合在指定区域内进行距离和面积计算。

不能直接把经纬度的“度”当成“米”。因此 `validate_spatial_dataset()` 默认要求：

```python
require_projected=True
```

当后续节点要计算米制距离、缓冲区或面积时，地理坐标系会被拦截。只做不涉及米制计算的基础数据检查时，可明确传入：

```python
require_projected=False
```

这不是自动投影。校验函数只报告问题，不擅自选择目标投影坐标系。

## 四、GeoDataFrame.crs

GeoPandas 官方文档说明，`GeoDataFrame.crs` 返回：

```text
pyproj.CRS | None
```

它表示活动 geometry 列的 CRS。`None` 说明数据没有声明 CRS。

注意：

- `set_crs()` 是声明或覆盖 CRS，不改变坐标值。
- `to_crs()` 才是把几何坐标转换到另一个 CRS。
- 错把 `set_crs()` 当作投影转换会让数据位置产生严重错误。

## 五、PyProj CRS 解析

代码使用：

```python
CRS.from_user_input(value)
```

PyProj 可以统一解析 EPSG 编号、Authority 字符串、WKT、PROJ 字符串和已有 CRS 对象。

校验结果分两类：

- `missing_crs`：输入是 `None`
- `invalid_crs`：输入存在，但 PyProj 无法解析

解析成功不代表适合当前分析。还要通过 `crs.is_projected` 判断是否为投影坐标系。

## 六、缺失几何、空几何与无效几何

这三种情况必须分开：

### 1. 缺失几何

几何值是 `None`。使用：

```python
geometry.isna()
```

它通常表示记录没有空间对象。

### 2. 空几何

对象存在，但不包含任何坐标，例如 `POLYGON EMPTY`。使用：

```python
geometry.is_empty
```

GeoPandas 官方文档明确指出，`is_empty` 不会把 `None` 当作空几何。

### 3. 无效几何

几何包含坐标，但违反拓扑规则，例如多边形边界自相交形成蝴蝶结。使用：

```python
geometry.is_valid
```

官方文档示例还表明，`None` 的 `is_valid` 结果也是 `False`。所以代码先检查 `isna()`，再检查 `is_empty`，最后检查 `is_valid`，才能返回准确错误类型。

## 七、错误合同

`SpatialValidationError` 不只返回一段文本，还保存机器可判断的错误码：

| 错误码 | 含义 |
|---|---|
| `empty_dataset` | 数据集没有记录 |
| `missing_geometry_column` | 没有活动 geometry 列 |
| `missing_fields` | 缺少业务必需字段 |
| `missing_crs` | CRS 为 `None` |
| `invalid_crs` | CRS 无法解析 |
| `crs_not_projected` | 米制分析使用了非投影 CRS |
| `null_geometry` | 存在 `None` 几何 |
| `empty_geometry` | 存在 EMPTY 几何 |
| `invalid_geometry` | 几何拓扑无效 |

字段缺失错误会保存 `missing_fields`，几何错误会保存 `row_indices`，便于 API 层映射为清晰提示或审计记录。

## 八、成功结果

合法数据返回 `SpatialValidationResult`：

- 标准化 CRS 字符串
- 是否为投影坐标系
- 要素数量
- 活动几何列名称
- 几何类型列表
- 已检查的业务字段列表

这是一个小型、可序列化的校验审计结果，不保存整个 GeoDataFrame。

## 九、为什么不自动修复几何

当前闸门只验证，不自动调用 `make_valid()` 或 `buffer(0)` 修复。

原因是自动修复可能：

- 改变多边形边界
- 把一个对象拆成多个对象
- 改变面积
- 掩盖源数据质量问题

合规分析中，修复必须是显式步骤，并记录原始几何、修复方法、修复结果和数据版本。

## 十、测试覆盖

新增 12 项测试：

- 合法投影数据通过
- 缺 CRS 被拒绝
- 非法 CRS 被拒绝
- 地理坐标系不能直接进入米制分析
- 非米制闸门可接受地理坐标系
- 缺业务字段被拒绝
- 缺活动 geometry 列被拒绝
- `None` 几何被单独识别
- EMPTY 几何被单独识别
- 自相交多边形被拒绝
- 空数据集被拒绝
- 校验不会修改输入 GeoDataFrame

项目全量测试结果：

```text
98 passed, 1 existing Starlette warning
```

## 十一、当前边界

- 尚未从 `DatasetManifest.location` 读取真实空间数据
- 尚未比较数据实际 CRS 与 Manifest 声明 CRS 是否一致
- 尚未为中国不同地区自动选择合适投影
- 尚未实现几何修复流程
- 尚未实现缓冲区、相交、包含和叠加分析
- 尚未将验证结果写入 `GISEvidence`
- 尚未接入 LangGraph 的强制条件边

## 十二、下一步业务入口

下一步应建立 Spatial Dataset Gateway，并把验证接入固定节点：

```text
geometry_dataset_id
  -> DatasetManifest
  -> SpatialDatasetGateway.load()
  -> validate_spatial_dataset()
  -> GISEvidence
  -> 只有 READY 才进入分析节点
```

## 官方文档

- GeoPandas `GeoDataFrame.crs`：https://geopandas.org/en/stable/docs/reference/api/geopandas.GeoDataFrame.crs.html
- GeoPandas `GeoSeries.is_valid`：https://geopandas.org/en/stable/docs/reference/api/geopandas.GeoSeries.is_valid.html
- GeoPandas `GeoSeries.is_empty`：https://geopandas.org/en/stable/docs/reference/api/geopandas.GeoSeries.is_empty.html
- PyProj `CRS`：https://pyproj4.github.io/pyproj/stable/api/crs/crs.html

## 十三、SpatialDatasetGateway 实现补充

空间验证函数现已接入业务数据流：

```text
CandidateParcel.geometry_dataset_id
  -> 在 AgentState.datasets 中查找 DatasetManifest
  -> SpatialDatasetGateway.load(manifest)
  -> 校验必需字段、实际 CRS、Manifest CRS 和几何
  -> 查找目标 parcel_id
  -> 生成 GISEvidence
```

`SpatialDatasetGateway` 是供应商无关接口。当前 `MockSpatialDatasetGateway` 只从内存加载 GeoDataFrame，并返回深拷贝，确保测试不会修改源数据。后续文件和 PostGIS 实现只需遵守相同的 `load()` 契约。

状态映射规则：

- 未声明 `geometry_dataset_id`：`MISSING`
- 未找到 DatasetManifest：`MISSING`
- Gateway 中不存在数据：`MISSING`
- 数据集中不存在目标 `parcel_id`：`MISSING`
- 缺 CRS、缺字段、CRS 不一致或几何非法：`INVALID`
- 全部校验通过且存在目标地块：`READY`

成功的 `GISEvidence` 会保存地块编号、数据集 ID、标准化 CRS、几何有效性和目标地块要素数量。失败原因保存在 `notes`，并带有稳定错误码。

当前 Gateway 仍是 Mock：尚未读取真实文件或 PostGIS，也尚未执行缓冲区、相交和叠加分析。项目全量测试现为 `108 passed, 1 existing warning`。

## 十四、确定性 GIS 分析补充

`calculate_spatial_metrics()` 已实现可复用的确定性空间指标：

- 地块面积，单位公顷
- 地块周长，单位米
- 指定缓冲距离
- 缓冲后总面积，单位公顷
- 与上下文图层相交的要素数量
- 到上下文图层最近要素的距离

所有距离和面积计算都要求投影坐标系。地块目标只接受 `Polygon` 或 `MultiPolygon`，避免对点、线计算无业务意义的地块面积。

`run_gis_analysis()` 是状态层入口。它只接受 `GISEvidence.READY`：证据缺失、证据非法、Manifest 缺失、Gateway 数据消失或再次校验失败都会抛出 `GISAnalysisBlockedError`，不会继续生成指标。

状态入口当前只回写地块自身的面积、周长和缓冲区指标。相交数量与最近距离已经由纯函数实现并测试，但需要先建立约束图层的 Manifest 和类型契约，才能接入业务状态，避免把任意图层误当作法定约束。

本阶段新增 11 项测试，项目全量达到 `119 passed, 1 existing warning`。

## 十五、约束图层契约与空间观察

本阶段在确定性 GIS 指标之上增加了约束图层契约与空间观察能力，建立如下数据流：

```text
ConstraintLayerSpec
-> DatasetManifest
-> SpatialDatasetGateway
-> 空间数据校验
-> 相交/邻近计算
-> ConstraintObservation
-> GISEvidence
```

这里产出的是可审计的空间事实，不是法规判断。`triggered=True` 仅表示配置的空间条件被命中，例如地块与某图层相交，或者距离某类要素不超过阈值；是否属于禁止、限制、提示或允许情形，仍需要后续版本化 `RuleDefinition` 和 `RuleEngine` 结合政策依据判断。

### 15.1 约束图层类型

`ConstraintLayerType` 当前定义五类业务图层：

- `land_use`：规划用地性质。
- `ecological_protection`：生态保护空间。
- `farmland_protection`：耕地保护空间。
- `development_boundary`：城镇开发边界。
- `sensitive_receptor`：学校、医院、居住区等敏感目标。

枚举限制了系统允许处理的图层语义，避免用任意字符串绕过类型校验。但枚举名称本身不携带法律结论，同一图层在不同地区、项目类型和规则版本下可能对应不同处置要求。

### 15.2 空间关系

`SpatialConstraintRelation` 支持两种确定性关系：

- `intersects`：判断候选地块是否与约束图层相交，以相交要素数大于零作为命中条件。
- `within_distance`：计算候选地块到约束图层最近要素的距离，以距离小于或等于配置阈值作为命中条件。

契约通过 Pydantic 保证配置自洽：

- `within_distance` 必须声明正数 `distance_threshold_m`。
- `intersects` 禁止声明距离阈值。
- 适用项目类型和必需字段不能为空，也不能包含重复值。
- 未知图层类型、未知空间关系和多余字段会在进入分析前被拒绝。

### 15.3 ConstraintLayerSpec

`ConstraintLayerSpec` 描述“要观察什么以及如何观察”，主要字段包括：

- `constraint_id`：稳定的约束配置标识。
- `display_name`：便于人工查看的名称。
- `layer_type`：约束图层业务类型。
- `dataset_id`：关联的空间数据集。
- `relation`：相交或邻近关系。
- `applicable_project_types`：适用的项目类型白名单。
- `required_fields`：分析前必须存在的业务字段。
- `distance_threshold_m`：邻近关系使用的距离阈值。

分析入口会先按 `ProjectType` 过滤配置。商场专用约束不会误用于物流园，反之亦然。相同批次中重复的 `constraint_id` 会被拒绝，以保证观察结果可唯一追踪和覆盖更新。

### 15.4 ConstraintObservation

每个候选地块、每条约束生成一条 `ConstraintObservation`，保存：

- 候选地块和约束标识。
- 图层类型、数据集标识与数据版本。
- 使用的空间关系和分析 CRS。
- 相交要素数量。
- 最近要素距离。
- 邻近阈值（如果适用）。
- 空间条件是否命中。

保存 `dataset_version` 与 `analysis_crs` 是为了使结果可复现、可审计。只保存 `triggered` 布尔值会丢失判断依据，无法解释结果来自哪个版本的数据、使用什么坐标系以及实际距离是多少。

### 15.5 分析入口与阻断条件

`run_spatial_constraint_analysis()` 复用现有 `SpatialDatasetGateway`、空间校验器和确定性指标函数，不重复实现数据读取与几何算法。它只接受目标地块 `GISEvidence.status == READY` 的状态。

下列情况会抛出 `ConstraintAnalysisBlockedError`，不会生成观察结果：

- 地块 GIS 证据缺失，或状态为 `MISSING/INVALID`。
- 候选地块未声明 `geometry_dataset_id`。
- 目标或约束数据集缺少 `DatasetManifest`。
- Gateway 找不到数据集。
- 数据缺 CRS、CRS 不匹配、使用地理坐标系、缺少字段或几何无效。
- 目标数据集中找不到对应 `parcel_id`。
- 约束图层无法计算最近距离。

约束图层与地块 CRS 不同时会先转换到地块的投影 CRS，再计算相交和米制距离。输入 `AgentState` 和源 `GeoDataFrame` 不会被原地修改；重复运行同一 `constraint_id` 时替换旧观察，而不是累积重复记录。

### 15.6 当前业务边界

当前模块负责回答“空间上发生了什么”，例如：

```text
地块 A01 与生态图层相交 1 个要素，最近距离为 0 米。
```

当前模块不能直接回答：

```text
地块 A01 违反生态保护规定，因此项目不合规。
```

第二种表述需要政策来源、规则版本、适用行政区、适用项目类型、规则条件和结论等级。下一阶段应建立：

```text
ConstraintObservation
-> RuleDefinition
-> RuleEngine
-> PolicyEvidence
-> AnalysisResult
```

POI 软评分也不能替代空间约束或政策规则。POI 用于商业便利性、交通可达性等选址偏好；空间观察记录确定性 GIS 事实；RuleEngine 才负责将事实映射为带依据的业务结论。

### 15.7 测试验收

本阶段新增 13 个测试用例，覆盖：

- 相交关系的命中与不命中。
- 邻近阈值两侧的判断。
- 相交与邻近配置的参数互斥。
- 不适用项目类型的约束跳过。
- `MISSING/INVALID` GIS 证据阻断。
- 缺少约束数据 Manifest 阻断。
- 无效约束几何阻断。
- 重复执行时替换同一观察。
- 输入状态不可变。

定向测试 `48 passed`，项目全量测试达到 `132 passed, 1 existing warning`。现有 warning 来自 FastAPI 测试依赖中的 Starlette/httpx 兼容性提示，与本阶段空间约束实现无关。
