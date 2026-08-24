# 可靠性、人工复核与运行可观测性说明

## 目标

本次交付增强选址运行链路的故障表达、在线 POI 保护、人工复核和阶段耗时观测。它不改变 GIS、POI、政策规则或评分算法，也不新增生产阈值和自动选址结论。

## 运行状态与阶段 trace

`SiteSelectionRunService` 为一次运行记录以下应用阶段：

1. `workflow`：确定性的选址工作流。
2. `human_review`：从 Evidence Review 构造人工复核状态。
3. `explanation`：可选 LLM 证据复述；未配置时为 `skipped`。
4. `report`：可选 DOCX 报告生成；未配置时为 `skipped`。
5. `total`：本次 API 运行的总耗时与最终状态。

每条 `RunStageTrace` 只包含：

- `stage`
- `status`: `succeeded / failed / skipped`
- `elapsed_ms`
- `error_type`

失败 trace 只保存异常类型，不保存异常消息、连接串、密钥或上游响应正文。工作流返回值会重新经过 `AgentState` 校验，非法返回不会让 Redis 状态停留在 `running`，而是写入显式 `failed` 状态和 trace。

LLM 解释失败不会篡改确定性分析结果：运行仍可为 `completed`，但 `explanation.status=failed` 且对应阶段 trace 为 `failed`。报告生成失败会使整个运行失败，因为已承诺的报告产物没有完成。

## Evidence Review 与人工复核边界

人工复核状态为：

- `not_required`：当前证据审查没有 warning。
- `pending`：存在 warning，等待人员确认已查看证据。
- `acknowledged`：人员已经确认查看；该动作不等于批准、合规或选址推荐。

`reason_codes` 来自 Evidence Review 的 warning `issue_code`，例如：

- `policy_rule_match`
- `poi_fixture_fallback`

`EvidenceReviewReport.requires_human_review` 必须与 warning 是否存在一致。`blocked` 报告不能降级成人工“已阅”；它会阻断运行最终化并产生失败 trace。这样可以避免把证据链缺失误表示为一个普通确认动作。

新增接口：

```text
POST /site-selection/runs/{run_id}/human-review/acknowledge
```

请求体可带可选 `note`。首次确认会更新 Redis 运行详情并追加 `human_review_acknowledged` 事件，事件明确记录：

```text
boundary=acknowledgement_not_compliance_approval
```

重复确认是幂等的，不追加重复事件，也不覆盖第一次确认的备注。对 `not_required` 或缺失复核状态的运行确认会返回冲突，而不是伪造确认状态。

## 在线 POI 重试与熔断

`RetryingCircuitBreakerPOIAdapter` 包装已有在线 Adapter，职责是：

- 只重试 `POIAvailabilityError`；
- 使用有上限的指数退避；
- 达到连续失败阈值后临时打开 circuit；
- circuit 打开时不再发送 HTTP 请求；
- 恢复窗口结束后允许探测请求，成功后关闭 circuit；
- `POIResponseError` 等畸形响应不重试、不回退，避免隐藏数据契约错误。

它可以继续由 `FallbackPOIAdapter` 包装。在线来源限流或暂时不可用时，Fixture 回退仍会显式记录：

- `fallback_from`
- `fallback_reason`
- Fixture provider、数据集版本和查询时间

Evidence Review 检测到 Fixture 回退后生成 `poi_fixture_fallback` warning，因此结果需要人工复核。真实在线失败不会被伪装成正常在线数据。

## API 与 Workbench

`SiteSelectionRunResponse` 新增：

- `human_review`
- `trace`

Streamlit 工作台会在 `pending` 时显示复核警告和“确认已阅”按钮，在 `acknowledged` 时显示非批准边界；阶段 trace 放在可展开表格中。工作台仍只通过 FastAPI 操作，不直接读写 Redis 或业务模块。

## 端到端场景

新增可靠性端到端测试覆盖：

1. 正常运行完成且不需要人工复核。
2. 政策规则命中后运行完成，但人工复核为 `pending`。
3. 必要空间字段缺失时运行失败并留下失败 trace。
4. 高德限流后 circuit 打开，Fixture 回退及审计 warning 均可追踪。

额外覆盖：阻断证据不得确认、工作流非法返回、重复确认幂等、畸形 POI 响应不重试、熔断超时后恢复探测。

## 验证结果

- 可靠性定向测试：`45 passed`。
- 项目 `.venv` 完整回归：`425 passed in 7.23s`。
- Compose 已重新构建 API、MCP 和 Workbench 镜像；PostGIS、Redis、API、MCP 与 Workbench 均成功启动。
- 容器 smoke：`project_types=2, candidates=4, reports=2, mcp_tools=6`，两份解释均为 `generated`。
- 浏览器实测商场运行产生 `policy_rule_match` 待复核状态，并显示 workflow、human_review、explanation、report、total 五阶段 trace。
- “确认已阅”操作成功写回，界面明确显示“该操作不代表合规批准”。

## 非生产声明

- Fixture POI 数量仍只适合稳定演示和回归测试，不足以支撑现实选址判断。
- 本次没有扩充合成 POI 来制造“数据更真实”的错觉；后续应优先完善真实在线 POI 的覆盖、采样策略、缓存和来源质量评估。
- 高德 GCJ-02 仍经明确转换后才归一化为 WGS84；不得直接标成 EPSG:4326。
- 人工“已阅”不是政策审批、合规结论或项目推荐。
- 默认应用仍 fail-closed；只有显式配置的运行时才能执行选址分析。
