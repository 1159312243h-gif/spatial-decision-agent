# 空间数据 CRS 与几何有效性校验

> 日期：2026-08-18
>
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
