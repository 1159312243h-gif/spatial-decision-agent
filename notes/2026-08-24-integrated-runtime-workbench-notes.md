# 2026-08-24 集成运行时与工作台说明

## 目标

本日交付将既有 PostGIS、Redis、MCP、多 Agent、GIS/POI/政策证据、RulePack、评分和 Word 报告串成一个显式 fixture 演示运行时，并增加 API 驱动的 Streamlit 工作台。

## 架构边界

- 默认 `app.main:app` 在未设置 `SITE_SELECTION_RUNTIME_MODE` 时继续 fail-closed，运行接口返回 503。
- 只有 `SITE_SELECTION_RUNTIME_MODE=fixture` 才迁移数据库、写入合成数据、连接 Redis 并注册商场与物流园运行时。
- fixture 初始化失败时应用启动失败，不回退到内存假运行时。
- Streamlit 只调用 FastAPI，不直接访问数据库、Redis 或业务函数。
- MCP 作为独立容器公开 6 个白名单工具，共用 PostGIS 数据。
- LLM 解释是确定性分析完成后的附加产物，不参与评分、排序、规则判断或证据审查。

## 数据链路

1. `data/fixtures/spatial_layers.json` 使用 `EPSG:32651` 描述四个合成图层。
2. `PostgresSpatialRepository` 将 geometry 统一归一化写入 `EPSG:4326`。
3. `StoredPostGISSpatialDatasetGateway` 通过固定 SQL 和 `:layer_id` 绑定参数读取统一表。
4. Gateway 根据 `DatasetManifest.crs` 重投影回 `EPSG:32651`，供工作流计算面积与距离。
5. POI fixture 明确为 WGS84/EPSG:4326，经 `POINormalizer` 后去重写入 PostGIS，供 MCP 查询；工作流使用相同 fixture adapter 生成带来源时间的 POI 证据。
6. Redis 保存运行状态、事件、幂等记录和 POI 预览缓存。
7. 完成状态生成 DOCX，Redis 记录报告 URL 与 SHA-256。

## LLM 解释约束

- 输入只包含结构化 GIS 指标、POI 指标与来源、规则引用和对比结果。
- 每条候选地说明必须引用输入中真实存在的 `evidence_reference`。
- 输出必须完整覆盖候选地块。
- 禁止总体合规结论、批准意见或选址推荐。
- 未配置 LLM 时响应为 `not_configured`；模型或校验失败时响应为脱敏的 `failed`，确定性分析仍保持完成。

## 验证

- 全量测试：`403 passed in 5.77s`。
- `docker compose config --quiet`：通过，沙箱仅提示无权读取用户 Docker 配置文件。
- 真实容器 smoke：当前桌面沙箱 Docker API 审批失败，需在项目根目录由用户执行。
- Streamlit 依赖未安装到当前测试 venv；其纯客户端与呈现 helper 已通过测试，Compose 镜像会按 `requirements.txt` 安装。

## 非生产声明

- 所有新增空间、政策、规则与评分边界均带 `fixture` 标识，仅用于工程链路演示。
- 商场与物流园分值不可解释为生产选址阈值。
- GCJ-02 仍不得直接标记为 EPSG:4326。
