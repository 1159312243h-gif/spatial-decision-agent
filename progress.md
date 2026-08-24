# 学习进度

## 2026-08-22 真实用地 Provider 与证据分级

- 新增 OSM Overpass 商业/零售用地和商业建筑多边形 Provider；上海示例范围真实 smoke 返回 181 个边界内可解析要素。
- 候选发现升级为“权威图层 -> 公开观察 -> 商业代理 -> 市场网格”，OSM 候选使用真实多边形质心和投影面积。
- 新增 `authoritative/public_observation/synthetic/unspecified` 证据等级；OSM 只支持商业初筛，完整合规继续阻断。
- 新增 Redis 用地范围缓存、共享代理、只读 smoke 脚本和权威空间文件导入脚本。
- Bootstrap 对权威 PostGIS 图层执行来源、许可、字段、米制 CRS、Fixture 和元数据防伪校验。
- Workbench 展示用地证据等级、来源、许可和缓存命中；Agent 手册新增第 36 节源码与设计说明。
- 聚焦测试 `56 passed`；扩展回归 `574 passed`，3 个 MCP Client 用例因当前解释器缺少 `pywintypes` 未通过，与本阶段代码无关。

## 候选位置自动发现

- 咖啡店、便利店支持按 WGS84 范围发现候选。
- 从带 Polygon 几何和用地属性的机会单元池筛选，不生成无法追溯的任意坐标。
- 用地 `excluded` 在评分前硬过滤，缺失用地证据时关闭失败。
- 每个 POI Profile 分组只做一次范围查询，本地计算候选邻域指标。
- 支持最小间距去重、证据来源、截断/降级警告、Agent 计划与节点轨迹。
- Workbench 发现后立即显示候选地图，人工确认后才进入正式异步分析。
- 用地资料不足时支持商业用地代理和纯市场探索网格，两个降级层级均禁止提交正式分析。
- 支持 `strict`、`commercial_land_proxy`、`market_exploration` 三种降级策略。
- 候选发现新增独立范围 POI 背景层：查询全部 30 个审核类别、矩形裁剪、跨分组去重、类别筛选和来源/截断展示；评分证据保持不变。
- Compose 默认 POI Provider 改为 `auto`，在线优先、Fixture 显式降级。

## 2026-08-03

> 本次任务跨午夜完成，首次提交完成于 2026-08-04 00:01。

### 今日完成

- 安装并验证了 Python 3.12.4
- 创建了 Python 虚拟环境 `.venv`
- 成功激活虚拟环境
- 验证了虚拟环境中的 Python 和 pip
- 创建了本地 Git 仓库
- 配置了 `.gitignore`
- 建立了 Agent 学习项目骨架
- 创建了 `src`、`tests` 和 `notes` 目录
- 编写并运行了最小 Python 程序
- 编写了项目 `README.md`
- 完成了第一次 Git 提交
- 修正了 Git 提交者的姓名和邮箱

### 项目运行结果

执行命令：

`python -m src.main`

输出结果：

`Agent learning project is ready.`

### 今日理解

- Python 虚拟环境依赖电脑中已经安装的基础 Python
- 虚拟环境用于隔离不同项目的 Python 依赖
- 激活虚拟环境后，`python` 和 `pip` 会指向 `.venv`
- `git init` 用于初始化本地 Git 仓库
- `git status` 用于查看文件状态
- `.gitignore` 用于排除不需要提交的文件
- `git add` 用于把修改加入暂存区
- `git diff --staged` 用于检查即将提交的内容
- `git commit` 用于把暂存区内容保存为一个版本
- Git 不会直接跟踪空目录，可以使用 `.gitkeep` 保留目录

### 遇到的问题

#### 1. PowerShell 无法识别 `py`

- 现象：执行 `py --version` 时提示无法识别命令
- 原因：系统中没有可用的 Python Launcher
- 解决方式：安装 Python 3.12.4，并改用 `python` 命令
- 是否理解：已理解，`py` 和 `python` 是不同的命令入口

#### 2. 无法激活虚拟环境

- 现象：PowerShell 提示系统禁止运行脚本
- 原因：PowerShell 执行策略阻止了 `Activate.ps1`
- 解决方式：执行 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
- 是否理解：已理解，该设置只对当前 PowerShell 窗口有效

#### 3. 把 `.gitignore` 内容输入了终端

- 现象：PowerShell 把 `.venv/` 等内容当作命令执行
- 原因：没有区分终端命令和文件内容
- 解决方式：使用 VS Code 打开 `.gitignore`，在文件编辑区填写并保存
- 是否理解：已理解，终端用于执行命令，编辑器用于修改文件

#### 4. 进入 Git 分页查看器

- 现象：执行 `git diff --staged` 后进入帮助页面
- 原因：Git 使用分页查看器展示较长内容
- 解决方式：按 `q` 退出分页查看器
- 是否理解：已理解

#### 5. Git 自动使用了 unknown 用户名

- 现象：第一次提交提示提交者姓名和邮箱由 Git 自动生成
- 原因：仓库没有配置 Git 用户身份
- 解决方式：为当前仓库配置用户名和邮箱，并修改首次提交
- 是否理解：已理解，Git 提交记录包含作者身份

### 验收结果

- `python --version` 正常输出 Python 3.12.4
- `python -m src.main` 可以正常运行
- `git log --oneline -1` 可以看到首次提交
- `.venv` 没有被 Git 跟踪
- `git status` 显示工作区干净

### 明日任务

- 学习 Git 分支、合并和冲突
- 复习 Python 函数、列表、字典和集合
- 编写一个简单的数据统计程序
- 继续保持每完成一个步骤就进行验证的习惯

## 2026-08-04

> 本次任务跨午夜至 2026-08-05 完成。

### 今日完成

- 检查并恢复 Python 虚拟环境
- 学习 `branch`、`switch`、`merge`、`pull`、`push`
- 创建 `practice/git-branch`
- 在两个分支修改同一行
- 主动制造并解决一次合并冲突
- 创建 merge commit `9f35813`
- 编写 `practice/python_basics.py`
- 完成图层总数、类型集合、缺失 CRS 和按类型统计
- 完成 12 项正常与异常输入检查
- 使用 `.venv` 运行并输出 `All checks passed.`

### Git 理解

- 分支是指向提交的可移动引用
- `merge` 将另一个分支历史合入当前分支
- 两个分支修改同一行时 Git 无法自动选择，因此产生冲突
- `HEAD` 区域来自当前 `master`
- 分隔线下方来自 `practice/git-branch`
- 解决冲突后需暂存并创建 merge commit
- `pull` 获取并整合远程修改，`push` 上传本地提交；本次未实际执行

### Python 理解

- 列表保存有顺序的多个图层
- 字典保存单个图层字段和统计结果
- 集合保存不重复的图层类型和已见名称
- 循环逐项处理，条件判断负责校验异常输入

### 发现并修复的问题

- 缺少字段可能产生难理解的 `KeyError`，改为明确的 `ValueError`
- 重复图层可能导致重复计数，增加 `seen_names` 检查
- 非列表和非字典输入增加 `TypeError`
- 空列表返回合法的空统计结果

### 工具问题

- Codex 审批服务返回 403，无法代替用户写入 `.git` 或启动用户目录 Python
- 通过 VS Code 完成 Git 操作，并使用项目 `.venv` 手动运行脚本

### 后续任务

- GitHub 上传前检查作者邮箱和敏感信息
- 决定仓库公开或私有
- 将 `master` 统一为 `main`
- 创建 GitHub 空仓库并首次 `push`
- 后续再进入 GIS Agent 正式开发

## 2026-08-05

### 今日完成

- 理解了 LLM、Token、Prompt、Tool、Agent 和 Skill 的关系
- 创建了 `Layer` 类，练习了类、对象、属性和函数参数
- 将图层统计代码拆分为 `models.py`、`service.py` 和 `io.py`
- 使用 `pathlib` 和 `json` 完成 UTF-8 JSON 文件读取
- 使用 `try/except` 处理文件不存在和 JSON 格式错误
- 创建了 `run_layer_stats.py` 程序入口
- 使用 `unittest` 完成 6 项自动化测试
- 创建 GitHub 私有仓库并完成首次推送

### 今日理解

- 模块是一个 Python 文件，包是组织多个模块的目录
- 类是创建对象的模板，对象保存具体数据
- `raise` 用于主动报告错误，`try/except` 用于处理可预期错误
- JSON 的 `null` 读取到 Python 后会变成 `None`
- Tool 负责执行动作，Skill 负责描述可复用的执行方法
- `git commit` 保存到本地，`git push` 才会上传到 GitHub

### 测试结果

- 正常图层数据：通过
- 空列表：通过
- 缺少字段：通过
- 重复图层：通过
- JSON 格式错误：通过
- 文件不存在：通过
- 总计 6 项测试，全部通过

### 遇到的问题

- Codex 审批服务返回 403，Git 写操作改在本地 PowerShell 执行
- 首次推送 GitHub 时网络连接超时，重新连接后推送成功
- 修改 Git 用户邮箱只影响未来提交，不会自动修改历史提交

### 明日任务

- 复习模块、包、类和异常处理
- 学习如何为函数和类编写更完整的测试
- 根据后续计划继续完善图层数据处理能力

## 2026-08-06

### 今日完成

- 复习了 Python 模块、类、异常处理和 JSON 读取
- 练习了 `git diff`、`git diff --stat` 和 `git diff --staged`
- 审查了 AI 生成的图层统计代码
- 记录了编码、可变默认参数、文件关闭、变量初始化、字段校验、统计效率和输出顺序等 7 个问题

### Git 知识点

- `git diff` 查看工作区中尚未暂存的修改
- `git diff --stat` 查看修改文件和行数摘要
- `git diff --staged` 查看暂存区中准备提交的修改
- 文件暂存后，修改会从普通 diff 转移到 staged diff

### 遗留任务

- Hot100 第 1 题和第 49 题顺延至 8 月 7 日完成

## 2026-08-07

### 今日完成

- 审查了简历中的项目经历，确认保留两个项目：
  - 多类型建设项目选址与国土空间合规决策 Agent
  - 地理图表理解与问答评测系统
- 删除或暂不使用无法证明的训练规模、准确率和性能提升数据
- 明确简历描述应采用“完成了什么 + 使用什么技术 + 解决什么问题 + 可验证结果”的结构
- 学习了 Self-Attention 中 Q、K、V 的作用
- 理解了 `QKᵀ → 缩放 → Softmax → 乘 V` 的计算流程
- 理解了除以 `sqrt(d_k)` 是为了防止点积过大导致 Softmax 饱和

### 今日理解

- Q 表示当前词想查询什么信息
- K 表示每个候选词用于匹配的特征
- V 表示匹配后实际提供的内容
- 每个词通过 Q 与所有词的 K 计算相关度，再加权汇总所有词的 V，因此能够融合上下文信息
- 简历中的数据必须能够通过代码、测试结果或实验记录证明，不能根据参考项目直接填写

### 遗留问题

- 两个简历项目还需要随着实际开发进度持续更新
- 项目性能指标应等测试脚本和评测数据完成后再补充
- Multi-Head Attention、位置编码和完整 Transformer 结构后续继续学习

### 下一步

- 开始 FastAPI 基础开发
- 实现 `/health`、`/documents` 和 `/chat` 三个接口
- 完成参数校验、接口测试和 Swagger 联调
## 2026-08-08

### 今日完成

- 安装并验证 FastAPI、Uvicorn、pytest 和 httpx
- 建立 `app/api`、`app/schemas` 和 `app/services` 分层目录
- 实现 `GET /health` 健康检查接口
- 实现 `POST /documents` 文档元数据桩接口
- 实现 `POST /chat` 选址问题桩接口
- 使用 Pydantic 校验缺失字段、空问题和非法项目类型
- 通过 Swagger 完成三个接口的手工联调
- 新增 6 项 API 自动化测试
- 运行全部测试，12 项测试全部通过
- 完善 README 中的安装、启动、接口和测试说明

### 今日理解

- FastAPI 用于把 Python 函数组织成可以通过 HTTP 调用的后端接口
- Uvicorn 负责启动服务并监听请求
- Swagger 是接口说明和调试工具，不负责理解自然语言
- Pydantic 负责把不合法的请求拦截在业务逻辑之前
- `api` 层定义 HTTP 路由，`schemas` 层定义数据结构，`services` 层处理业务逻辑
- 当前 `/documents` 和 `/chat` 是桩接口，尚未接入真实 Agent、RAG、数据库或 GIS 分析
- 自动化测试可以重复验证正常请求和异常输入，比只依赖 Swagger 手工点击更可靠

### 遇到的问题

- `api/documents.py` 与 `schemas/documents.py` 内容一度放反，导致 Uvicorn 重载失败和 Swagger 白屏
- 通过检查 Uvicorn 终端和模块内容定位问题，交换文件内容后恢复
- 直接遍历 `app.routes` 读取 `path` 时遇到 `_IncludedRouter`，改用 `app.openapi()["paths"]` 检查公开接口
- pytest 出现 TestClient 依赖弃用 warning，但不影响当前 12 项测试结果，后续根据官方兼容说明统一处理

### 调整说明

- 因时间不足，跳过当天 ACM 和 Hot100 编程题，不补做、不挤占休息时间

## 本周总结（2026-08-03 至 2026-08-09）

### 本周完成

- 创建并激活 Python 3.12 虚拟环境，掌握依赖隔离的基本方法
- 创建本地 Git 仓库，完成首次提交、分支切换、合并和冲突处理
- 创建 GitHub 私有仓库，配置远程地址并完成多次 push
- 学习 Python 函数、列表、字典、集合、模块、包、类、异常处理和 JSON 读取
- 将图层统计脚本拆分为模型、文件读取、业务统计和程序入口
- 完成正常数据、空数据、字段缺失、重复图层、无效 JSON 和文件不存在测试
- 学习 `git diff`、`git diff --stat` 和 `git diff --staged`
- 完成一次 AI 生成代码审查，记录编码、可变默认参数、资源关闭、变量初始化和效率等问题
- 完成两数之和与字母异位词分组练习，理解哈希表和哈希键设计
- 审查简历项目真实性，删除无法证明的训练规模和效果指标
- 学习 Self-Attention 中 Q、K、V、缩放、Softmax 和上下文融合
- 建立 FastAPI 接口骨架，完成三个接口、Pydantic 校验、Swagger 联调和 API 自动化测试

### 本周掌握

- 能解释工作区、暂存区、本地仓库和远程仓库的区别
- 能完成 Git 分支开发、制造冲突、解决冲突、提交和推送
- 能使用 Python 包和模块拆分代码，并使用异常表达无效输入
- 能读取 UTF-8 JSON 并将字典数据转换为对象
- 能使用 unittest 和 pytest 验证正常路径及异常路径
- 能解释 FastAPI、Uvicorn、Swagger、Pydantic 和桩接口各自的职责
- 能解释 Q、K、V 和除以 `sqrt(d_k)` 的直观原因

### 本周遗留问题

- 当前 FastAPI 接口没有真实文件上传、持久化和文档解析能力
- `/chat` 尚未接入 LLM、意图识别、RAG 或 GIS 工具
- 项目类型目前只支持 `shopping_mall` 和 `logistics_park`
- 测试客户端存在依赖弃用 warning，需要后续查阅官方兼容方案
- Multi-Head Attention、位置编码和完整 Transformer 结构仍需继续学习
- 简历中的项目效果指标需要等真实评测脚本和数据完成后补充

### 下周目标

- 学习 FastAPI 文件上传、配置管理和统一异常处理
- 为 `/documents` 增加真实文件接收与元数据处理
- 为 `/chat` 设计可扩展的意图和候选地块输入结构
- 开始搭建项目文档解析与检索的最小流程
- 保持 Git 小步提交、pytest 回归测试和 progress 记录
- 恢复算法训练，但不挤占主项目开发和休息时间


## 2026-08-10

### 今日完成

- 复习 Token、上下文、消息角色和 Temperature
- 使用 OpenAI Python SDK 调用公司九功模型
- 通过原生 Responses API 完成最小聊天函数
- 使用 `.env` 管理真实配置，并使用 `.env.example` 提供配置模板
- 实现保留最近若干轮对话的滑动窗口
- 完成物流园选址需求的任务拆分练习
- 模型成功输出 5 个有顺序的执行步骤

### 今日理解

- Token 是模型处理文本的基本单位
- 上下文由程序保存并在下一次请求中重新发送
- System 规定规则，User 提出需求，Assistant 表示历史回复
- Temperature 控制输出的随机程度，不代表模型的聪明程度
- `.env` 保存真实配置且不能提交
- `.env.example` 只能保存变量名称和占位符
- 滑动窗口能够限制历史消息数量，避免上下文无限增长
- Responses API 使用 `client.responses.create()` 发起请求

### 遇到的问题

- `practice.llm_api` 尚未创建，首次运行出现 `ModuleNotFoundError`
- 创建 Python 包和 `client.py` 后解决
- 最初误将真实配置写入 `.env.example`
- 在 Git 暂存前替换为占位符，避免进入仓库
- CC Switch 使用原生 Responses 格式，因此将调用方式从 Chat Completions 改为 Responses API

### 遗留问题

- 当前滑动窗口按照对话轮数限制，还没有按照 Token 数量限制
- LLM API 和上下文模块还没有自动化测试
- `/chat` 接口尚未接入真实模型调用

### 下一步

- 为上下文窗口编写单元测试
- 处理模型超时、鉴权失败和空回复异常
- 根据后续计划决定是否将真实模型接入 FastAPI `/chat`

## 2026-08-11

### 今日完成

- 整理 Token、上下文窗口、消息角色和 Temperature 四张知识卡
- 阅读并解释现有 `ConversationContext` 滑动窗口代码
- 确认滑动窗口保留系统指令和最近完整问答，超出轮数后自动淘汰最旧轮次
- 审查现有 `chat()` 函数的输入、输出、API 参数和上下文保存流程
- 初步学习 Prompt 模板、Zero-shot、Few-shot 和结构化输出的基本关系

### 今日理解

- Token、系统指令、历史消息、当前问题和模型输出都会占用上下文容量
- 当前滑动窗口按照完整问答轮数裁剪，并不按照真实 Token 数裁剪
- 系统消息通过 `instructions` 单独传入，不会随旧对话一起被淘汰
- Prompt 模板把稳定的任务规则与动态用户输入分开
- Zero-shot 只提供任务说明，Few-shot 额外提供少量标准输入输出示例

### 当前边界

- 当前窗口按对话轮数限制，尚未按真实 Token 数限制
- 滑动窗口没有旧消息摘要、持久化和多用户会话隔离
- LLM API 和上下文模块还没有自动化测试

### 下一步

- 深入整理 Prompt 模板、Few-shot、输出约束和非法 JSON
- 建立选址需求 Pydantic 输出模型骨架
- 完成一次合法 JSON 的正常解析

## 2026-08-12

### 今日完成

- 深入学习 Tokenizer、BPE、BBPE、WordPiece、Unigram 和 SentencePiece
- 学习 Greedy Search、Beam Search、Top-k、Top-p 和 Temperature 等生成策略
- 阅读并整理前辈的 Prompt 工程资料，形成适用于当前选址 Agent 的项目版笔记
- 整理 Zero-shot/Few-shot、输出约束、非法 JSON 三张知识卡
- 建立 `SiteSelectionRequirement` Pydantic 输出模型骨架
- 使用 `model_validate_json()` 完成一次合法 JSON 到 Pydantic 对象的正常解析

### 今日理解

- Tokenizer 负责在文本与 Token ID 之间编码和解码，生成策略负责选择下一个 Token
- Prompt 模板负责固定角色、任务、输入边界、约束和输出协议
- Few-shot 通过少量标准输入输出示例帮助模型稳定字段映射和缺失值处理
- 模型返回 JSON 文本后，仍需经过 JSON 语法解析和 Pydantic 字段校验
- 非法 JSON 属于语法错误；字段缺失、类型错误和取值越界属于 Pydantic 校验错误
- 当前 Pydantic 模型表示选址需求，不代表已经生成合规审查结论
- 当前项目使用 Responses API，不能直接照抄 Chat Completions 的结构化输出代码

### 当前边界

- 已完成手工构造的合法 JSON 解析，尚未接入真实 API 返回文本
- 尚未实现非法 JSON、字段缺失和类型错误测试
- 公司模型接口是否支持服务端原生 Structured Outputs 尚未验证
- Prompt 只能约束模型输出倾向，不能代替 GIS 计算、政策证据和规则引擎

### 下一步

- 建立可复用的选址需求提取 Prompt 模板和 Few-shot 示例
- 将真实 API 返回的 JSON 文本解析为 Pydantic 对象
- 覆盖合法 JSON、非法 JSON、缺字段、错误类型和额外字段测试
- 设计明确的解析失败提示与有限重试策略

## 2026-08-13

### 今日完成

- 验证 `SiteSelectionRequirement` 对正常 JSON、非法 JSON 和缺失字段的处理
- 学习 Function Calling 的六步调用链路并完成闭卷流程图
- 整理 Function Calling 学习文档，明确模型、应用程序、Pydantic 和工具函数的职责
- 实现不使用 `eval()` 的安全计算器，支持加、减、乘、除
- 使用工具白名单和 Pydantic 校验工具名称及参数
- 实现 Responses API 完整工具调用循环
- 完成计算问题、普通对话、缺少参数及其他异常边界测试
- 使用公司模型端点完成一次真实 Function Calling 调用

### 今日理解

- 模型只负责选择工具、生成参数和组织最终回答，不直接执行 Python 函数
- JSON Schema 向模型描述参数合同，Pydantic 在程序端校验实际参数
- 应用程序必须校验工具白名单和参数后才能执行函数
- 工具结果需要回传模型，模型才能基于真实结果生成最终回答
- 工具执行失败时必须回传明确错误，不能伪造计算结果
- `eval()` 会执行任意 Python 表达式，不适合作为计算器实现

### 接口实测

- 当前公司 Responses 兼容接口支持函数工具定义、`function_call` 和 `function_call_output`
- 普通 HTTP 请求不支持使用 `previous_response_id` 串联响应，该字段仅支持 Responses WebSocket v2
- 第二次请求显式携带用户消息、`function_call` 和 `function_call_output` 后，真实调用成功
- 实测问题为“请计算 18.5 乘以 4”，最终回答为“18.5 × 4 = 74”

### 测试情况

- 计算器与工具调用专项测试共 10 项，全部通过
- 已覆盖正常计算、普通对话、缺少参数、非法操作、除零、额外参数、未注册工具和空输入

### 当前边界

- 当前只注册了计算器工具，尚未接入选址 Agent 的 GIS、政策检索和规则工具
- 当前调用上下文由程序显式回传，尚未使用 WebSocket v2
- 尚未验证连续多次工具调用、并行工具调用和接口超时后的重试策略
- 工具调用循环尚未接入 FastAPI `/chat`

### 下一步

- 为完整项目运行全部测试并检查 Git 差异
- 后续将工具注册表扩展为可复用结构
- 按项目计划逐步接入选址数据查询、GIS 分析和政策检索工具
- 在明确会话管理与错误处理方案后，再将真实工具调用接入 FastAPI `/chat`

## 2026-08-14

### 今日完成

- 为 `SiteSelectionRequirement` 增加 5 项自动化测试
- 覆盖正常 JSON、非法 JSON、缺少必填字段、错误字段类型和额外字段
- 为工具执行结果增加 `status`、`elapsed_ms` 和 `error_type` 记录
- 使用摘要形式记录 Pydantic 校验错误，避免写入完整输入值
- 增加未知工具的安全错误记录测试，确认未注册工具不会执行
- 运行完整测试，28 项全部通过
- 整理 Transformer、Token Embedding、位置编码、Self-Attention、Multi-Head Attention、FFN、残差连接和归一化学习资料
- 整理 10 张知识卡、5 条评测题、参考答案和评分点

### 今日理解

- Token ID 是词表中的离散索引，Embedding 是可参与模型计算的连续向量
- 初始 Token Embedding 不等于完整上下文语义，后者由 Transformer 层逐步形成
- 位置信息用于区分 Token 顺序，RoPE 通常通过旋转 Q、K 影响注意力分数
- Attention 负责 Token 之间的信息交互，FFN 负责逐 Token 的非线性特征加工
- 残差连接提供信息和梯度的直接路径，归一化用于稳定数值尺度
- 工具错误记录应保留错误类型和必要摘要，不应记录密钥或完整敏感输入

### 测试情况

- 项目完整测试：28 项通过
- 新增结构化输出测试：5 项通过
- 工具调用测试：5 项通过
- 现有 Starlette TestClient 依赖弃用 warning 仍存在，不影响当前测试结果

### 今日未验收

- 未进行 Transformer、Embedding、Attention 的独立闭卷作答
- 按今日调整取消 5 分钟讲解录音，不记录为已完成
- 尚未实现 3 个工具的统一注册接口和多工具路由

### 下一步

- 实现 3 个离线确定性工具的统一注册表、参数模型和路由测试
- 验证不同问题能够选择正确工具，非法参数和未知工具不会执行
- 后续结合 LangGraph 学习补画选址任务分解 DAG
- 算法练习在独立时段补充，不挤占项目主线
## 2026-08-15

### 今日完成

- 复核 `SiteSelectionRequirement` Pydantic 结构化输出测试，合法 JSON、非法 JSON、缺字段、错误类型和额外字段共 5 项通过
- 整理 Tool、Skill、Function Calling 的定义、区别、调用关系、安全边界和选址项目映射
- 实现通用 `ToolDefinition` 与 `ToolRegistry`
- 统一注册 `calculator`、`current_date`、`project_type_profile` 三个 Tool
- 使用各 Tool 的 Pydantic 参数模型生成 JSON Schema 并执行应用侧二次校验
- 加入未知工具拦截、重复注册拦截、工具超时、安全错误摘要、耗时与错误类型记录
- 将原生 Responses Function Calling 循环改为从 Registry 获取 Tool Schema 和执行实现
- 保持原有 `run_tool_calling()` 调用方式兼容，并保留最大工具轮数限制
- 多工具专项测试 21 项通过
- 项目全量测试 38 项通过，保留 1 条已有 Starlette TestClient 弃用 warning
- 真实模型成功选择 `current_date`，返回 Asia/Shanghai 时区的 2026-08-15
- 真实模型成功选择 `project_type_profile`，返回物流园的基础审查重点

### 今日理解

- Skill 定义一类业务任务如何完成，Tool 执行一个确定性动作，Function Calling 让模型结构化提出工具名称和参数
- 模型只提出 `function_call`，真正的白名单检查、参数校验、执行和结果回传都由应用程序负责
- ToolRegistry 是工具执行边界，不是 Agent、Skill 或 Workflow
- JSON Schema 可以约束模型输出，但应用侧仍必须使用 Pydantic 重新校验
- 固定业务前置检查应由 Skill 或 DAG 强制执行，不能全部交给模型自由选择
- 项目类型查询只返回静态示例 Profile，不代表完成政策查询、GIS 分析或合规判断

### 遇到的问题

- Windows Python 环境缺少 IANA `tzdata`，`ZoneInfo("Asia/Shanghai")` 抛出 `ZoneInfoNotFoundError`
- 当前日期工具只支持 Asia/Shanghai 和 UTC，因此改用标准库固定 UTC+8 与 UTC+0 偏移，不增加新依赖
- 当前线程超时可以及时返回错误，但不能强制终止已开始运行的线程；真实外部工具仍需要底层客户端或 worker 超时

### 测试情况

- Pydantic 结构化输出测试：5 项通过
- 计算器与原 Function Calling 回归：11 项通过
- 多工具定向测试：21 项通过
- 项目全量测试：38 项通过，1 条既有弃用 warning
- 真实接口：计算器、日期查询、物流园项目类型查询均已完成验证

### 当前边界

- 当前三个 Tool 均为本地确定性示例工具
- `project_type_profile` 使用静态映射，只支持 `shopping_mall` 与 `logistics_park`
- 尚未实现 `ProjectIntakeSkill`、PlanningIntentAgent、LangGraph DAG、GIS Tool、政策 RAG 和 RuleEngine
- `/chat` 尚未接入真实多工具 Function Calling 循环
- 尚未实现持久化 ToolCall 审计、跨进程取消和真实外部服务重试

### 下一步

- 检查并提交 ToolRegistry、调用循环、测试、学习文档和本日进度
- 后续进入 Agent 编排前，先定义 ProjectRequest、ProjectProfile、DatasetManifest 等领域合同
- 学习 CRS、投影和几何有效性后，再实现空间数据验证 Tool
- 保持 LLM、Skill、Tool、RuleEngine 和 Orchestrator 的职责边界
## 2026-08-16

### 今日完成

- 整理 Agent、ReAct、Function Calling、ToolRegistry 与 LangGraph 的概念关系和职责边界
- 整理 LangGraph State、Node、Edge 三张知识卡及闭卷复述提纲
- 安装并确认 LangGraph `1.2.11`，同步加入 `requirements.txt`
- 使用 `TypedDict` 定义最小 `AgentState`，包含消息、当前步骤、待执行工具、工具结果、错误、调用次数与上限、运行状态和最终答案
- 为 `messages` 和 `tool_results` 配置追加 reducer，确保节点返回增量时保留历史记录
- 使用 `create_initial_state()` 拦截空输入和非法工具调用上限，并避免跨请求共享可变列表
- 搭建 `START -> input -> model -> tool/final -> END` 最小 LangGraph 图
- 实现模型后的条件路由：普通回答直接结束，工具请求进入工具节点，超出调用上限时在执行前终止
- 在工具节点复用现有 `ToolRegistry`，未重复实现计算器、日期和项目类型工具逻辑
- 将工具成功结果和安全错误同时写回模型消息与结构化 `tool_results`
- 覆盖普通对话、正确工具调用、未知工具、非法参数和循环上限五类图测试
- AgentState 与 LangGraph 图专项测试 15 项通过
- 项目全量测试 53 项通过，保留 1 条已有 Starlette TestClient 弃用 warning
- 真实模型通过 LangGraph 成功选择日期工具，并返回 2026 年 8 月 16 日（Asia/Shanghai）

### 今日理解

- State 是整张图共享的数据合同，Node 只完成一个步骤，Edge 和条件路由负责决定下一步
- `Annotated[list, operator.add]` 表示节点返回的列表增量会追加到旧状态，而不是覆盖历史记录
- `pending_tool_calls` 表示当前待办，执行后必须覆盖为空，不能像历史消息一样持续追加
- Tool Schema 只是提供给模型的工具说明，应用侧仍必须通过 ToolRegistry 白名单和 Pydantic 进行二次校验
- 工具结果必须以 `function_call_output` 回传模型，模型才能基于真实 Observation 生成最终回答
- 调用上限应在工具执行前判断，防止超限调用产生副作用
- LangGraph 负责状态和流程编排，不等于业务 Agent，也不取代 Tool、RuleEngine 或安全校验
- 当前系统保存可审计的消息、调用、结果和错误，不保存模型原始内部推理文本

### 测试情况

- `tests/test_agent_state.py`：10 项通过
- `tests/test_agent_graph.py`：5 项通过
- 项目全量测试：53 项通过，1 条既有弃用 warning
- 真实接口：LangGraph 日期工具调用成功

### 当前边界

- 当前图只接入本地计算器、日期和静态项目类型三个示例工具
- `TypedDict` 不提供 Pydantic 式运行时字段校验，公共入口依靠 `create_initial_state()` 建立合法初始状态
- 公共入口能拦截空输入；若绕过入口直接以畸形 State 调用编译图，固定的 `input -> model` 边仍有改进空间
- 尚未实现 checkpoint、跨请求持久化、人工审批和生产级调用审计
- 尚未实现 PlanningIntentAgent、ProjectIntakeSkill、GIS Tool、政策 RAG、RuleEngine 和空间合规 DAG
- FastAPI `/chat` 尚未接入 LangGraph
- 当天算法题、周总结和知识卡抽查尚未完成，不能计入今日成果

### 下一步

- 完成本周周总结：列出完成项、未完成项、3 个问题和下周入口
- 抽查至少 10 张知识卡，重点复述 Agent、ReAct、State、Node、Edge、Reducer 和工具安全边界
- 检查本次代码与文档差异，提交并推送
- 后续定义 ProjectRequest、ProjectType、ProjectProfile 和 DatasetManifest，再进入选址业务图

### 周总结补充

- 已完成 2026-08-10 至 2026-08-16 周总结，整理本周完成项、未完成项、三个主要问题和下周入口
- 已建立 10 张闭卷知识卡及评分点
- 本次跳过闭卷知识抽查，未进行评分和错题纠正，不将知识抽查计入已完成项
## 2026-08-17

### 今日完成

- 明确“ProjectRequest -> ProjectProfile -> POIQuery -> POIFeatureSet -> 业务 AgentState -> AnalysisResult”字段流
- 新建独立 `practice/site_selection` 业务包，未修改昨天的通用 LangGraph 工具状态
- 定义 `ProjectType`、`ProjectRequest`、`CandidateParcel`、`DatasetManifest`
- 使用枚举拒绝未知项目类型和未知数据来源
- 校验候选地块坐标、正面积、唯一编号和带时区请求时间
- 定义 `POIQuery`、`POIRecord`、`POISourceMeta`、`POIFeatureSet`
- 校验 POI 查询类别、半径、条数、供应商、查询时间和来源记录数量
- 配置商场与物流园两个 ProjectProfile，每类包含 6 组 POI 类别、半径、指标和软评分权重
- 校验每个 Profile 至少 5 组、分组唯一且权重之和为 1
- 定义选址业务 `AgentState`、`GISEvidence`、`POIEvidence`、`PolicyEvidence` 和 `AnalysisResult`
- 校验请求、Profile、候选地块、证据和结果之间的交叉引用
- 建立 FastAPI、PostGIS、Redis Compose 骨架和三个健康检查
- 建立 Dockerfile、`.dockerignore` 与 `.env.compose.example`
- 确认 API Key、数据库密码和 Redis 密码只从环境变量读取，示例文件无真实密钥
- 新增 14 项数据契约测试并全部通过
- 使用 YAML 解析器确认 Compose 包含 `api/postgis/redis` 三个服务且均有健康检查

### 今日理解

- 数据契约负责在数据进入节点前拒绝非法类型、缺失字段和交叉引用错误
- Profile 是项目类型对应的查询与软评分配置，不是最终合规规则
- POI 原始记录、来源元数据和计算指标应分层保存，避免丢失可追溯性
- DatasetManifest 记录数据来源和版本，不应保存任何真实凭据
- 通用工具调用 AgentState 与选址业务 AgentState 职责不同，应通过模块边界隔离
- LLM 负责理解与解释，项目类型、半径、权重和引用一致性由枚举与 Pydantic 确定性校验
- Compose 骨架只是运行配置，只有容器实际启动并通过健康检查后才能算运行验收

### 测试情况

- 新增数据契约测试：14 项通过
- 新代码 `compileall`：通过
- Compose YAML：成功解析，三个服务均包含健康检查
- 原项目最近基线：53 项通过
- 合并后的完整 67 项测试：复制到项目后待运行
- Docker 容器：当前环境没有 Docker CLI，尚未启动验收

### 当前边界

- 尚未执行真实 POI 查询
- 尚未连接 PostGIS 和 Redis
- 尚未实现软评分计算、GIS 分析、政策 RAG 和 RuleEngine
- 业务 AgentState 尚未接入 LangGraph
- 商场和物流园 Profile 是学习用静态配置，尚未经过真实业务标定
- 不得将 POI 软评分描述为法定合规结论

### 下一步

- 将文件复制到项目后运行完整测试，确认 67 项通过
- 本机具备 Docker Desktop 后运行 Compose 配置和健康检查
- 实现 `ProjectTypeRouter`、`ProfileRegistry` 和 POIQuery 构造函数
- 再进入 CRS、投影、字段完整性和几何有效性校验

## 2026-08-18

### 今日完成

- 安装并验证 WSL 2、Docker Desktop 和 Docker Compose
- 解决 Docker Hub 连接超时，使用国内镜像下载并在本地标记 Redis、PostGIS 和 Python 镜像
- 使用真实 `.env` 通过 Compose 配置校验，未覆盖或提交已有 LLM 密钥
- 成功构建并启动 FastAPI、PostGIS、Redis 三个容器
- 确认三个服务均为 `healthy`，`/health` 返回 `status=ok, version=0.1.0`
- 正常停止三个容器，保留容器和数据卷
- 实现 `ProfileRegistry`，统一管理项目类型与 Profile 的白名单映射
- 实现 `ProjectTypeRouter`，将商场和物流园请求路由到对应 Profile
- 实现 `build_poi_queries()`，按候选地块和 Profile 分组生成确定性 POI 查询
- 实现 `ProjectIntakeSkill`，建立包含 Profile 和 POI 查询的 `DATA_PENDING` 业务状态
- 实现供应商无关的 `POIGateway` 接口和确定性 `MockPOIGateway`
- 实现 POI 类别、半径、数量上限过滤及距离排序
- 实现数量、密度、最近距离和平均距离指标计算
- 实现 POI 查询结果写回 `POIFeatureSet`、`POIEvidence` 和业务 `AgentState`
- 新增 19 项入口、路由、查询生成和 Mock POI 测试

### 今日理解

- 未知项目类型和空候选地块应由 Pydantic 在进入路由前拒绝
- `ProfileRegistry` 管理配置白名单，`ProjectTypeRouter` 只负责选择 Profile
- `ProjectIntakeSkill` 是确定性业务能力封装，不等于自主 Agent
- POI 查询生成适合写成纯函数，便于复现、审计和单元测试
- `POIGateway` 隔离上层业务与高德、百度、PostGIS 等具体供应商
- Mock 的价值是验证业务编排与供应商实现解耦，不是伪装成真实空间分析
- POI 数量和距离属于辅助证据，不是法定合规结论
- 状态执行函数返回重新校验的新对象，避免原地修改造成难以追踪的副作用

### 测试与运行情况

- 选址契约、入口和 POI 定向测试：33 项通过
- 项目全量测试：86 项通过
- 既有 Starlette 弃用 warning：1 条，与本次修改无关
- `git diff --check`：无实际空白错误，仅有 Windows LF/CRLF 提醒
- Compose：API、PostGIS、Redis 均通过健康检查
- API 健康接口：`status=ok, version=0.1.0`

### 当前边界

- 当前 POI 数据来自 Mock，尚未调用真实地图 API 或 PostGIS 查询
- Mock 距离是预先标准化的测试字段，尚未执行真实坐标距离计算
- 尚未实现 CRS、空间字段和几何有效性校验
- 尚未实现缓冲区、叠加、相交和空间约束分析
- 尚未实现 POI 软评分归一化、政策 RAG、RuleEngine 和最终结论
- 静态 Profile 仍是学习配置，尚未经过真实业务标定

### 下一步

- 学习 GeoPandas 与 PyProj 中 CRS、投影和几何有效性的基本边界
- 实现 `spatial/validate.py`
- 拦截缺 CRS、缺必需字段、空几何和无效几何数据
- 为合法与非法空间数据编写单元测试
- 通过验证的数据再进入 GIS 分析节点

### 空间校验补充

- 安装并验证 GeoPandas 1.1.4、PyProj 3.7.2 和 Shapely 2.1.2
- 阅读 GeoPandas 与 PyProj 官方文档，确认 CRS、缺失几何、空几何和无效几何的 API 行为
- 新建 `practice/site_selection/spatial/validate.py`
- 使用 `CRS.from_user_input()` 统一解析 CRS，区分缺 CRS 与非法 CRS
- 默认禁止地理坐标系直接进入米制距离和面积分析
- 校验活动 geometry 列、业务必需字段和非空数据集
- 分别拦截 `None` 几何、EMPTY 几何和拓扑无效几何
- 使用结构化错误码、缺失字段和错误行号记录失败原因
- 合法数据返回可序列化的 `SpatialValidationResult` 审计摘要
- 新增 12 项空间数据校验测试并全部通过
- 项目全量测试提升至 98 项通过，仍只有 1 条既有 Starlette warning

#### 空间模块边界

- 当前只执行验证，不自动投影或修复几何
- 尚未加载真实空间文件或 PostGIS 图层
- 尚未对比 DatasetManifest 声明 CRS 与实际 CRS
- 尚未将校验结果写入 `GISEvidence` 或 LangGraph 节点
- `requirements.txt` 已增加空间依赖，下次 Docker 运行新代码前需要重新构建 API 镜像

#### 空间模块下一步

- 定义 `SpatialDatasetGateway`
- 通过 `geometry_dataset_id` 和 `DatasetManifest` 加载空间数据
- 将校验成功或失败映射到 `GISEvidence`
- 仅允许 `EvidenceStatus.READY` 的数据进入 GIS 分析节点

### 空间数据 Gateway 补充

- 定义供应商无关的 `SpatialDatasetGateway.load()` 接口
- 实现返回 GeoDataFrame 深拷贝的 `MockSpatialDatasetGateway`
- 通过 `geometry_dataset_id` 在业务状态中匹配 `DatasetManifest`
- 校验实际 CRS 与 Manifest 声明 CRS 一致性
- 将缺引用、缺 Manifest、缺数据和缺目标地块映射为 `GISEvidence.MISSING`
- 将缺 CRS、缺字段、CRS 不一致和非法几何映射为 `GISEvidence.INVALID`
- 将通过全部验证的目标地块映射为 `GISEvidence.READY`
- 成功证据记录数据集 ID、CRS、几何有效性和目标要素数量
- 保持输入 AgentState 和源 GeoDataFrame 不被原地修改
- 新增 10 项 SpatialDatasetGateway 测试，项目全量达到 108 项通过

#### Gateway 当前边界

- 当前只实现 Mock，尚未读取真实文件或 PostGIS
- 尚未把 `GISEvidence.READY` 接入 GIS 分析节点
- 尚未计算缓冲区、相交、面积和距离指标

### 确定性 GIS 分析补充

- 实现 `SpatialMetrics` 结构化指标模型
- 实现地块面积、公顷换算和投影坐标系周长计算
- 实现指定距离缓冲区及缓冲后总面积计算
- 实现与上下文图层的相交要素计数和最近距离计算
- 强制地块目标只能是 Polygon 或 MultiPolygon
- 非正缓冲距离会在执行前被拒绝
- 实现 `run_gis_analysis()` 状态入口，仅接受 `GISEvidence.READY`
- `MISSING/INVALID` 证据会抛出 `GISAnalysisBlockedError` 并阻断分析
- READY 后数据消失或再次校验失败同样阻断，不使用过期证据继续计算
- 指标写入新的 `GISEvidence`，不原地修改 AgentState 或源 GeoDataFrame
- 新增 11 项确定性 GIS 分析测试，项目全量达到 119 项通过

#### 分析层当前边界

- 状态节点目前只回写地块自身面积、周长和缓冲区指标
- 相交和最近距离纯函数已完成，但尚未建立约束图层 Manifest 契约
- 尚未实现规划、生态、耕地等具体规则和 RuleEngine
- 当前指标属于空间事实，不直接等于合规结论

### 约束图层契约与空间观察

- 新增 `ConstraintLayerType`，覆盖规划用地、生态保护、耕地保护、开发边界和敏感目标五类图层
- 新增 `SpatialConstraintRelation`，支持相交和阈值邻近两类空间关系
- 新增 `ConstraintLayerSpec`，校验项目类型、必需字段、空间关系和距离阈值
- 新增 `ConstraintObservation`，记录数据版本、分析 CRS、相交数量、最近距离、阈值和命中状态
- 将 `constraint_observations` 接入 `GISEvidence`，并校验观察记录必须属于同一候选地块
- 实现 `run_spatial_constraint_analysis()`，复用现有 Gateway、空间校验和确定性 GIS 指标
- 按项目类型过滤约束配置，非适用约束不会执行
- `MISSING/INVALID` GIS 证据、缺失 Manifest、无效几何和不可用数据均会阻断分析
- 重复执行同一约束时替换原观察，避免结果重复；输入状态和源数据保持不变
- 明确 `triggered=True` 只是空间条件命中，不等于违法、不合规或否决结论
- 新增 13 个约束契约与空间观察测试；相关定向测试 `48 passed`
- 项目全量回归 `132 passed, 1 existing warning`

#### 当前边界与下一步

- 当前只产出可审计空间事实，尚未生成政策结论
- 尚未实现版本化 `RuleDefinition`、法规依据映射和 `RuleEngine`
- 下一步建立 `ConstraintObservation -> RuleDefinition -> RuleEngine -> PolicyEvidence -> AnalysisResult` 链路

### 版本化 RuleEngine 与政策证据

- 新增 `PolicyReference`，记录政策标识、标题、发布机关、文号、条款、版本、行政区和来源 URI
- 新增版本化 `RuleDefinition`，支持适用项目类型、约束观察、期望值、有效日期和启用状态
- 新增 `RuleOutcome`：提示、需复核、受限和禁止；不提供自动合规通过等级
- 新增结构化 `PolicyFinding`，保存规则、政策、空间观察和数据版本的完整血缘
- 扩展 `PolicyEvidence`，增加 `evaluated_rule_ids` 和 `rule_findings`，同时保留原字符串字段兼容现有接口
- 实现 `evaluate_policy_rules()`，按项目类型和请求日期选择有效规则
- 同一 `rule_id` 存在多个同时有效版本时抛出 `RuleConfigurationError`
- 无适用规则、GIS 未就绪或缺少规则所需观察时抛出 `RuleEvaluationBlockedError`
- 未命中规则时明确记录“未命中不等于整体合规”
- 重复运行替换原政策证据，不修改输入 `AgentState`
- 当前测试只使用合成政策，不宣称任何真实法规结论
- 新增 15 项 RuleEngine 测试；定向组合测试 `42 passed`
- 项目全量回归 `147 passed, 1 existing warning`

#### 下一步

- 搭建业务 LangGraph，将 Intake、POI、GIS 校验、GIS 分析、空间约束和 RuleEngine 串成端到端最小图
- 将硬约束政策证据与 POI 软评分分离写入 `AnalysisResult`
- 真实法规规则录入前建立专业复核、版本发布和历史追溯机制

### 端到端选址业务 LangGraph

- 新增 `SiteSelectionWorkflowDependencies`，显式注入 POI Gateway、空间 Gateway、约束配置、版本化规则和缓冲距离
- 搭建 `POI -> GIS 校验 -> GIS 指标 -> 空间约束 -> RuleEngine -> AnalysisResult` 确定性 DAG
- 每个业务节点复用现有模块，不在工作流中重复实现 POI、GIS 或规则逻辑
- 为每个业务节点增加条件边，失败状态统一路由到 `failed -> END`
- 增加 GIS 强制证据门，任一候选地块为 `MISSING/INVALID` 时不进入分析节点
- 已知业务阻断保留可操作说明，未知异常只记录类型，避免敏感原始消息进入状态
- 新增 `assemble_analysis_results()`，要求 GIS、POI 和政策三类证据全部 READY
- GIS 硬事实、POI 软评分和政策规则证据在 `AnalysisResult` 中保持分离
- 当前缺少 POI 归一化评分规则时不伪造分数，写入明确 warning
- `COMPLETED` 仅表示图执行完成，不表示项目合规；当前 `conclusion` 保持为空
- 新增 10 项工作流与结果汇总测试；组合测试 `38 passed`
- 项目全量回归 `157 passed, 1 existing warning`

#### 下一步

- 定义商场与物流园分别适用的 POI 指标方向、归一化区间和评分版本
- 生成可解释的分组得分与 `POIEvidence.soft_score`
- 评分不得覆盖或抵消 `PolicyEvidence` 中的硬约束命中

### POI 查询分组契约

- 将 `POIQuery.group_key` 定义为必填非空字段
- `build_poi_queries()` 直接从 `ProjectProfile.poi_groups` 写入分组标识
- 后续评分逻辑可以通过结构化字段匹配分组，不再解析 `query_id`
- 商场与物流园生成的查询分组顺序分别与对应 Profile 保持一致
- 多候选地块场景下，每个“地块 + Profile 分组”组合唯一且完整
- 手工构造查询时缺少 `group_key` 会被 Pydantic 在进入 Gateway 前拒绝
- 更新 POI 契约、Intake、Gateway 及端到端工作流相关测试
- 定向组合测试 `44 passed`
- 项目全量回归 `158 passed, 1 existing warning`

#### 下一步

- 定义评分方向、归一化上下界、指标权重和缺失指标策略
- 本阶段尚未计算或写入任何 POI 软评分

### 版本化 POI 软评分契约

- 新增 `ScoreDirection`，显式区分越大越好和越小越好
- 新增 `MissingMetricPolicy`，仅支持默认阻断和显式零分
- 新增 `POIMetricScoringRule`，配置归一化上下界、方向、权重和缺失策略
- 新增 `POIGroupScoringConfig` 与 `POIScoringConfig`，记录项目类型和评分版本
- 组内指标权重必须合计为 1，重复指标和重复分组会被拒绝
- 实现 0-100 线性归一化与边界截断，拒绝 `NaN` 和无穷值
- 评分配置、POI 数据分组及指标必须与 `ProjectProfile` 完全一致
- 新增 `POIMetricScore`、`POIGroupScore` 和 `POIScoreReport`，保留原始值、权重、版本与数据来源
- 实现单候选地块纯函数 `score_poi_feature_sets()`
- 当前只使用合成阈值验证机制，尚未声明真实商场或物流园评分标准
- 新增 20 项评分契约测试
- 项目全量回归 `178 passed, 1 existing warning`

#### 下一步

- 设计商场与物流园评分配置草案及阈值校准依据
- 经确认后将 `POIScoreReport` 接入 `POIEvidence` 和业务 LangGraph
- POI 软评分始终不得抵消 `PolicyEvidence` 的硬约束命中

### POI 软评分状态服务与工作流接入

- 扩展 `POIEvidence`，新增完整的 `POIScoreReport` 评分血缘
- 校验评分报告地块、`soft_score` 与报告总分的一致性
- 新增 `score_poi_state()`，对所有候选地块执行确定性 POI 评分
- 要求每个候选地块存在唯一且 `READY` 的 POI 证据
- 评分服务返回新的 `AgentState`，不修改输入状态
- `SiteSelectionWorkflowDependencies` 新增必填版本化评分配置
- LangGraph 增加 `poi_scoring` 节点，流程更新为 `poi -> poi_scoring -> gis_collection`
- 将 `POIScoringError` 纳入已知业务错误并统一路由到失败状态
- 评分失败后不再执行 GIS、空间约束、政策规则和结果组装节点
- 正常结果将评分总分写入 `AnalysisResult.overall_soft_score`
- 评分报告保留版本、分组、指标原始值、方向、权重和数据来源
- 工作流测试继续验证软评分不会删除或抵消硬约束政策证据
- 当前 `demo-1.0` 和 `0-100` 阈值仅为合成测试配置，不代表真实业务标准
- 新增 7 项状态评分服务测试，并扩展端到端工作流测试
- 定向测试 `38 passed`
- 项目全量回归 `186 passed, 1 existing warning`

#### 下一步

- 为商场与物流园分别设计可审查的评分配置文件
- 记录阈值数据来源、适用范围、校准依据和发布版本
- 增加多候选地块排序，同时保持软评分与政策硬约束严格分离

### 多候选地块软评分对比

- 新增 `CandidateComparisonItem`，记录地块、软分名次、并列状态和政策结果等级
- 新增请求级 `CandidateComparisonReport`，记录项目类型、评分版本和排序依据
- 新增 `compare_candidate_results()`，按 POI 软评分降序生成稳定对比结果
- 完全同分使用标准竞赛排名，例如 `90, 90, 80 -> 1, 1, 3`
- 同分地块按 `parcel_id` 稳定排序；未在排名层隐式执行浮点舍入
- 要求所有候选地块使用同一个评分版本，混用版本时阻断
- 要求结果完整覆盖请求中的候选地块，拒绝缺失、多出和重复结果
- 要求每个地块同时存在软评分和完整 `POIScoreReport`
- 校验 `AnalysisResult.overall_soft_score`、`POIEvidence.soft_score` 和评分报告总分一致
- 对比项展示政策命中等级，但政策结果不参与软评分名次计算
- 明确软评分第一名仍可能带有 `prohibited`，排名不代表合规或推荐决定
- AgentState 新增 `comparison_report` 并校验其请求、类型和地块集合血缘
- LangGraph 末端更新为 `policy_rules -> results -> comparison -> END`
- 对比失败统一进入失败节点，并清空不完整结果与对比报告
- 比较服务返回新状态，不修改输入状态
- 新增 12 项候选对比测试并扩展端到端工作流断言
- 定向测试 `23 passed`
- 项目全量回归 `198 passed, 1 existing warning`

#### 下一步

- 将选址业务工作流接入应用服务/API 边界
- 定义请求响应 DTO、依赖提供器和业务错误映射
- 在真实配置完成审核前，不生成自动推荐或合规通过结论

### 选址 API、前置检查、结构化 Agent 与 Fixture POI

- 新增 `POST /site-selection/analyses`，通过 DTO 和应用服务调用既有确定性选址工作流
- 新增 `SiteSelectionRuntimeProvider`，隔离数据清单、网关、评分、约束和规则配置
- 默认未配置运行时安全返回 `503 runtime_unavailable`，不使用合成配置生成业务结果
- 输入错误返回 `422`，工作流业务阻断返回 `409`，未知服务异常清理后返回 `500`
- 成功响应要求全部候选地块结果和请求级候选对比报告完整
- 新增 `POST /site-selection/preflight`，供不完整项目草稿执行三态检查
- 新增 `SiteSelectionDraft` 和 `PreflightDecision`
- 前置检查支持 `ready / needs_input / unsupported` 三种结构化决策
- 缺少项目类型、候选地块、建设面积、几何数据引用或数据清单时返回具体字段，不继续猜测
- 商场和物流园继续复用既有 `ProfileRegistry` 路由，未知类型停止分析
- 新增 `OrchestratorAgent`、`SpatialAgent`、`PolicyAgent`、`ReviewAgent` 结构化输入输出边界
- 四个 Agent 复用已有 GIS、规则、结果组装和候选对比模块，不重复实现业务算法
- SpatialAgent 在 GIS 强制证据未就绪时阻断，PolicyAgent 要求显式版本化规则
- 新增 `POISourceAdapter` 协议和 JSON 驱动的 `FixturePOIAdapter`
- Fixture 包含 32 条合成 POI，覆盖商场和物流园 Profile 的全部类别
- Fixture 支持类别、Haversine 半径、数量限制和确定性顺序过滤
- POI 来源新增数据集版本和更新时间血缘，并校验时间包含时区
- 查询、底层数据集和返回记录使用防御性复制
- 新增只读 `SiteSelectionRuntimeRegistry`，按项目类型解析审核后的运行配置
- 注册表拒绝项目类型错配，未配置类型继续返回 `runtime_unavailable`
- FastAPI 新增 `create_app(runtime_provider=...)`，支持启动时显式注入注册表
- 默认应用仍使用未配置提供器，不隐式启用任何演示业务值
- 新增显式 Fixture HTTP 端到端测试，贯通 POI、GIS、规则、结果和候选对比
- Fixture 评分与规则只存在测试代码并带 `fixture-test` 标识，不代表真实业务配置
- 测试注册表只配置商场时，物流园分析继续返回 `503`
- 新增受根目录约束的 `FileSpatialDatasetGateway`
- 文件 Gateway 支持 GeoJSON、JSON、GeoPackage 和 Shapefile
- 文件 Manifest 必须使用相对路径，拒绝绝对路径、目录穿越和根目录外目标
- 文件缺失映射为 `MISSING`，来源、路径、格式或读取错误映射为 `INVALID`
- 读取错误只记录数据集编号和异常类型，不泄露文件内容或绝对根目录
- 每次加载返回新的 GeoDataFrame，不共享调用方修改
- 新增连接对象注入的 `PostGISSpatialDatasetGateway`
- PostGIS Manifest 只允许 `table` 或 `schema.table`，拒绝任意 SQL 片段
- schema 使用显式白名单，schema、table 和几何列使用严格标识符校验
- 数据库读取异常只保留数据集编号和异常类型，不泄露连接或服务端消息
- 依赖清单新增 `sqlalchemy` 和 `psycopg[binary]`，与 Compose 数据库 URL 对齐
- 已安装 `SQLAlchemy 2.0.52` 和 `psycopg 3.3.4`
- 已对 healthy 状态的 Compose PostGIS 执行真实实连冒烟测试
- 冒烟测试使用事务级临时空间表，成功验证 1 条 EPSG:32651 Polygon 数据并在提交后自动清理
- 真实 PostGIS 冒烟结果：`PostGIS smoke OK: rows=1, crs=EPSG:32651, geometry=Polygon`
- 本阶段未接入高德或 OSM，未新增真实政策规则、业务评分阈值或自动推荐结论
- 新增前置检查、Agent、Fixture、应用服务和 API 测试
- 定向测试 `38 passed, 1 existing warning`
- Fixture HTTP 端到端测试 `2 passed, 1 existing warning`
- 文件型空间 Gateway 定向组合 `45 passed`
- PostGIS 与其他空间 Gateway 定向组合 `61 passed`
- 项目全量回归 `269 passed, 1 existing warning`

#### 下一步

- 为正式 PostGIS 数据集定义受审核的表清单、schema 白名单和只读连接权限
- 在密钥管理和网络方案明确后接入真实 POI Adapter
- 明确生产数据、评分配置和政策规则的来源、版本、审核与发布流程

### 空间数据校验、PostGIS 持久化与 Redis 运行状态

- 空间质量门新增米制投影单位检查，缺少 CRS、空几何、无效几何和非米制投影均被结构化阻断
- 新增稳定 SHA-256 空间数据哈希，哈希包含 CRS、字段、属性和标准化几何，且不受行顺序和 DataFrame 索引影响
- 新增 `RawPOI`、`NormalizedPOI` 和 `POINormalizer`，统一来源、类别、地址、坐标系和带时区抓取时间
- 明确拒绝把 GCJ-02 直接标记为 EPSG:4326；当前固定数据统一使用 WGS84
- 新增版本化 PostGIS 迁移 `001_initial`，建立 `projects`、`spatial_layers`、`spatial_features` 和 `pois`
- Geometry 字段固定 SRID 4326，空间要素和 POI 均建立 GIST 索引
- 新增参数化 `PostgresSpatialRepository`，支持项目 upsert/读取、图层校验/哈希/重投影/整体替换和要素读取
- 新增参数化 `PostgresPOIRepository`，支持批量 upsert、按 `source + source_id` 去重读取和米制半径查询
- 新增 `RedisRunStateStore`，使用安全 namespace 保存结构化运行状态，校验 failed/error 一致性并显式设置 TTL
- Repository 通过依赖注入接收连接或客户端，不读取环境变量、不自行提交事务
- 新增数据库迁移、PostGIS Repository 和 Redis 状态冒烟脚本
- 定向存储测试 `39 passed`
- 真实 PostGIS 迁移 `PostGIS migration OK: version=001_initial`
- 真实存储冒烟 `features=1, pois=1, deduplicated=true`
- 真实 Redis 冒烟 `namespace=site_selection:smoke, ttl=300`
- 项目全量回归 `296 passed, 1 existing warning`
- 本阶段未接入高德或 OSM，未新增生产评分阈值、政策规则或自动推荐结论

#### 下一步

- 将 PostGIS Repository 和 Redis 状态存储注入选址应用服务与工作流运行边界
- 定义一次分析运行的合法状态转换、失败恢复和长期审计记录
- 在线 POI Adapter 接入前实现并审核 GCJ-02 真实转换和数据来源治理
- 生产部署前补充迁移工具、最小数据库权限、备份恢复、监控和密钥管理

### 2026-08-21 至 2026-08-23：运行态、在线数据、规则审查与报告交付

- 完成 LangGraph POI/GIS 真并发执行，并保持依赖 GIS 证据的 Policy 分支顺序。
- 完成 Redis 运行状态、事件、缓存、幂等键、TTL 和运行查询 API。
- 完成政策混合检索、可追溯引用、合成政策 Fixture。
- 完成高德与 Overpass POI Adapter、坐标转换、限流、错误映射和受控回退。
- 完成 YAML/JSON RulePack、可选 GIS+POI 组合评分和评分版本追踪。
- 完成 Evidence Review，覆盖 GIS、POI、政策、评分、引用及回退链路。
- MCP Server 增加可选 `policy_search`；新增带白名单、超时和结构化结果检查的 MCP Client。
- 完成审计型 Word 报告生成器与命令行入口；报告不输出总体合规结论或选址推荐。
- 全量回归 `373 passed`；报告可访问性审计高/中/低问题均为 0。
- PostGIS 查询一致性真实烟测已通过。
- Redis 运行态真实烟测已通过；当前环境缺少 LibreOffice，Word 报告尚未完成 PNG 视觉验收。
### 运行可靠性、人工复核与阶段可观测性

- 新增结构化运行阶段 trace，覆盖 workflow、human_review、explanation、report 和 total，仅保留耗时、状态与脱敏异常类型。
- 工作流返回值重新经过 `AgentState` 校验；非法返回、缺失 Evidence Review 或 blocked 审查均写入显式失败状态，不残留 running。
- 强化 Evidence Review 契约：`requires_human_review` 必须与 warning 一致，blocker 不得降级成人工确认。
- 新增 `not_required / pending / acknowledged` 人工复核状态和确认 API；确认只表示证据已阅，不代表合规批准或选址推荐。
- 人工确认写入 Redis 审计事件，重复确认幂等且不覆盖首次备注。
- 新增有界重试、指数退避和 circuit breaker POI 包装器；只重试可用性错误，不隐藏畸形响应。
- 在线 POI 不可用时可沿用显式 Fixture 回退，并通过 `fallback_from/fallback_reason` 和 `poi_fixture_fallback` warning 留痕。
- Streamlit 工作台增加待复核提示、确认已阅操作、非批准边界说明和阶段耗时表。
- 新增四类端到端可靠性场景以及阻断审查、非法工作流返回、幂等确认、熔断恢复等测试。
- 可靠性定向测试 `45 passed`，主仓库项目 `.venv` 完整回归 `425 passed in 7.23s`。
- Compose 五服务启动成功；双项目类型、四候选地、两报告和六 MCP 工具 smoke 通过。
- 浏览器实测待复核提示、五阶段 trace、确认已阅和“非合规批准”边界均正常。
- 当前未自动提交。
- Fixture POI 仍只用于稳定演示，不作为现实选址样本；后续继续推进真实 POI 覆盖与数据质量治理。
### 冻结评测、性能基线与交付文档

- 冻结 24 条选址评测，覆盖 4 条前置检查、6 条空间校验、3 条 Fixture POI、4 条 POI 故障、3 条政策 RAG 和 4 条完整工作流。
- 增加批量评测器与机器可读 JSON 结果，记录期望、实际、耗时和异常类型。
- 增加本机性能脚本，记录 GIS、POI、RAG 和完整评测批次的样本数、中位数及运行环境。
- 重写项目 README，补充启动、API、MCP、测试、Fixture 边界和安全约束。
- 新增架构说明、数据字典、Bad Case 报告和性能测量协议。
- 明确 Fixture POI 不具备真实选址参考性，人工确认不是合规批准，GCJ-02 不等于 EPSG:4326。
- 定向测试 `5 passed in 2.39s`，冻结评测 `24/24` 通过，全量回归 `430 passed in 8.39s`。
- 本机 Fixture 性能中位数：GIS `0.135ms`、POI `0.031ms`、RAG `0.033ms`、完整评测批次 `88.798ms`；这些数字不是生产 Benchmark。
### 2026-08-19：RQ 异步 Worker、取消与超时恢复

- 将选址运行拆分为 API prepare/enqueue 与 Worker execute 两个阶段，Compose 默认使用异步模式。
- 新增 RQ 队列适配器与独立 Worker 入口；任务载荷不包含数据库、Redis 或 LLM 凭据。
- Redis 运行状态新增 `cancelled`、`timed_out`，事件新增 `enqueued`、`cancelled`、`timed_out`。
- 新增取消 API；queued 使用 RQ cancel，running 使用 stop command，重复取消幂等。
- 取消先落 Redis 终态，防止 Worker 失败回调覆盖用户取消；迟到 Worker 不再发布结果。
- 关键状态转换使用 Redis Lua 原子比较更新，避免 Worker 启动、完成与取消之间的覆盖竞态。
- RQ job timeout 与失败回调写入脱敏终态，不覆盖已有终态。
- Workbench 支持 queued/running 展示、显式刷新和取消，未完成时不访问空 analysis。
- API 与 Worker 共享报告卷；同步模式保留给测试和显式本地调用。
- 新增异步队列、Worker、API、Workbench、Redis 状态与 Compose 契约测试。
- Fixture Smoke 兼容异步轮询；异步 Smoke 验证 HTTP 202、完整队列事件链和共享报告。
- RQ 2.11 真实入队发现并修复 `enqueue_call(job_timeout=...)` 参数错误，改为正式参数 `timeout=...`，并补充回归测试与安全 Smoke 诊断。
- 针对性测试 16 项通过；独立测试区完整 pytest 451 项通过。
- Docker Compose API、Worker、PostGIS、Redis 均健康；真实异步 Smoke 通过，事件链 4 个事件齐全并成功读取 DOCX 报告。
- Fixture 回归 Smoke 通过：2 类项目、4 个候选、2 份报告、6 个 MCP 工具，解释状态均为 `generated`。

### 丰富 Fixture 数据与多候选比较

- 将商场和物流园候选从每类 2 个扩展为每类 6 个，共 12 个差异化候选场景。
- 候选画像覆盖轨交餐饮、办公门户、成熟居住、竞争饱和、成长外围、高速、铁路、港口、城市配送、综合物流和航空联运等场景。
- 将 POI Fixture 扩展为 478 条、25 个类别，并按候选画像设置不同的类别数量和距离分布。
- 新增确定性生成器，统一生成候选目录、POI 和空间图层；回归测试逐项验证磁盘数据与生成器输出一致。
- 空间图层包含 12 个不同面积的候选多边形，以及每类项目 2 个约束要素。
- Fixture 来源元数据新增数据集总量、合成标记和质量说明，并与本次查询命中数分开。
- Workbench 候选比较增加候选名称、POI 命中组数、指标组总数、命中记录数和合成状态；POI 页展示来源与质量边界。
- DOCX 报告增加数据集总量、数据性质和质量边界，不把合成数据描述为真实城市覆盖。
- 评分归一化按查询面积和半径调整，商场与物流园使用不同的候选面积上界；12 个场景至少产生 4 种不同软评分。
- 冻结评测重新生成并通过 `24/24`；完整回归 `456 passed in 8.37s`。
- 478 条 POI 的本地 Fixture 查询中位数 `0.110ms`；该数字不是在线 Provider SLA 或生产容量声明。

### 工作台自动更新、分层地图与在线 POI 自动加载

- Workbench 对 queued/running 运行每 2 秒自动轮询，进入完成或失败终态后自动刷新完整结果；保留立即刷新和取消操作。
- 将无法区分点位的 `st.map` 替换为 PyDeck 分层地图：候选使用红色大标记和编号标签，POI 使用稳定类别颜色的小标记。
- 地图根据当前候选与 POI 范围自动计算中心和缩放级别，并提供候选名称、类别、Provider、距离与软评分悬浮信息。
- 新增 `fixture / auto / amap / overpass` 环境驱动 Provider 工厂；`auto` 优先使用已配置 Key 的高德，否则使用 Overpass。
- 高德查询保留分页和 GCJ-02 到 WGS84 转换；Overpass 为 25 个内部类别提供受控 OSM 标签映射。
- 在线 Provider 接入速率限制、有界重试、熔断、Redis TTL 缓存和显式 Fixture 回退，格式错误不会被回退掩盖。
- 在线结果按 `source + source_id` 参数化 upsert 到 PostGIS；缓存命中会重新绑定当前运行的查询身份。
- API 与 Worker Compose 服务统一透传 POI Provider 配置，避免预览和完整分析来源不一致。
- 新增 Provider 选择、缓存复用、高德优先、Overpass 自动加载、PostGIS 入库及地图层契约测试。
- 针对性测试 `35 passed`，完整回归 `461 passed in 9.26s`。

### 版本化 Agent DAG、节点轨迹与 POI 可信度门禁

- 新增 `AgentExecutionPlan` 与 `AgentSkillManifest`，把 Orchestrator、POI、Spatial、Policy、Merge 和 Review 定义为闭合无环的白名单 Skill DAG。
- POI 与 Spatial 节点显式属于同一并行组；Policy 依赖 Spatial，Merge 同时依赖 POI 与 Policy，Review 依赖 Merge。
- 新增 `AgentStepTrace`，返回节点角色、Skill 版本、依赖、并行组、状态、耗时和脱敏错误类型。
- 关键分支失败时，依赖节点按契约标记 `failed/skipped`；失败空间分支不会继续执行政策判定或证据审查。
- 当前业务 DAG 全部 `llm_allowed=false`，保持 LLM 解释层与确定性 GIS、POI、规则和排序分离。
- POI 来源新增 `available_record_count` 与 `is_truncated`，严格区分实际返回数、查询可用数、查询上限和完整数据集总量。
- Fixture、Overpass 和高德 Adapter 均记录截断；Evidence Review 新增 `poi_result_truncated` 与 `poi_synthetic_source` 警告。
- Workbench 新增 `Agent 运行`页签，展示执行计划、节点轨迹和质量门禁；POI 页对截断结果显示下界警告。
- DOCX 来源表增加返回/可用、查询上限和截断说明，来源摘要保留数量边界。
- 新增并扩展 DAG、失败路由、POI Adapter、来源契约、Evidence Review、Workbench 和报告测试；目标组合 `67 passed`。
- 尚未实现自然语言 PlanningIntentAgent、项目长期记忆、ScenarioVersion 与主图内政策 RAG，后续按 Agent 主线继续推进。

### 候选发现 POI 证据快照、正式分析复用与 Agent 手册完善

- 复盘真实运行：候选发现从缓存 OSM 获得约 1039 条范围 POI，但正式分析首次 OSM 调用失败并打开熔断，后续 48 个评分组降级 Fixture，最终只有较少合成 POI；确认“上图多、下方少且很快”是两次取证漂移，不是地图漏画。
- 新增 `CandidateDiscoveryPOISnapshot`，冻结候选发现的项目类型、候选集合、六个评分组、创建时间和内容 SHA-256；模型拒绝重复候选/评分组并设为只读。
- Redis Runtime Store 新增快照保存、读取和 TTL 查询，默认 `7200` 秒，且不允许长于运行状态 TTL。
- 候选发现服务在排序后保存快照，并返回 snapshot ID、SHA-256 与去重记录数；纯地图背景 POI 不进入评分快照。
- Workbench 确认候选时把 `poi_evidence_snapshot_id` 加入业务命令；RQ 只传 ID，不复制上千条 POI 或任何凭据。
- 同步分析与异步 Worker 都会校验项目类型、候选 ID、坐标和空间数据集，快照缺失/过期/错配时以 `409 analysis_blocked` 关闭失败。
- 新增 `SnapshotReusingPOIGateway`，按正式候选、类别、半径和 limit 本地裁剪宽域证据，重算距离与指标；仅快照缺少的新评分组才允许调用后备 Provider。
- `POISourceMeta` 新增 `evidence_snapshot_id/evidence_reused`；Run 顶层只有在工作流完成且最终结果确实含复用来源时才标记复用成功。
- 保留上游截断语义：宽域证据不完整时，本地少量命中仍声明 `available_record_count > record_count`，Evidence Review 继续按下界处理。
- 咖啡店和便利店正式 POI 查询上限均提升到 1000，不是只优化咖啡店；六个评分组保持不变。
- 新增快照校验和、只读、裁剪、缺组降级、Redis TTL、候选发现持久化、同步/异步复用、API 409、Workbench 与 Compose 契约测试。
- 定向回归 `83 passed`；配置 Windows `pywin32` DLL 搜索路径后，全量回归 `516 passed in 10.78s`。
- 全面更新 `agent-implementation-guide.md`，补充项目价值、竞品差异、Agent 必要性、记忆/缓存分层、性能优化、核心代码机制、近期增量、面试追问和后续路线。
- 同步更新 README、架构、候选发现、性能、数据字典和 Bad Case 文档；明确当前短期证据快照不等于自然语言会话记忆或项目长期记忆。
- 当前仍未接入真实用地、客流、租金、人口与经营数据；快照解决一次决策内的数据一致性和效率，不提升上游数据本身的准确度或覆盖率。

### Agent 框架 V2：Plan 驱动 LangGraph 编译

- 新增通用 `compile_agent_plan_graph()`，把审核后的 `AgentExecutionPlan` 作为运行图结构唯一来源。
- Plan 新增拓扑顺序约束；编译前严格校验计划节点与 Handler 一一对应，缺失 Handler 和计划外隐藏 Handler 均拒绝启动。
- 根节点、串行依赖、并行分支、多依赖 fan-in 和终点均从 `depends_on` 自动生成，不再在 `parallel_workflow.py` 手写第二套拓扑。
- 正式分析 LangGraph 的真实节点现与 Plan/Trace 完全一致：`intake`、`poi_evidence`、`spatial_evidence`、`policy_rules`、`merge_gate`、`review`。
- 保留 POI/Spatial 原生并发、Policy 对 Spatial 的依赖、Merge 双分支 barrier，以及失败后的 failed/skipped 传播。
- 新增拓扑顺序、图编译器和运行图一致性测试；框架定向测试 `13 passed in 1.27s`，完整回归 `521 passed in 10.14s`。
- 更新 Agent 手册与架构文档，明确候选发现仍待迁移到同一编译器，上层 Supervisor、ScenarioVersion、ConstraintAgent 和长期记忆仍属后续能力。

### 候选发现迁移到统一 Agent 图运行时

- 新增 `CandidateDiscoveryGraphState` 与 `build_candidate_discovery_graph()`，五个发现节点全部由审核 Plan 编译为同名 LangGraph 节点。
- `discovery_intake` 解析项目 Runtime/Profile；`land_use_gate` 与 `poi_market_evidence` 原生并行；`rank_diversify` 使用双依赖 barrier；`discovery_review` 保存快照并生成确认前报告。
- `CandidateDiscoveryService` 不再手工创建顶层业务线程池，只负责向图传入请求并验证最终 `CandidateDiscoveryReport`。
- 保留三级用地降级、范围 POI、评分、空间去重、快照 ID/SHA-256、Trace 顺序及 API 409/503 契约。
- 新增运行节点与 Plan 一致性测试，并用线程屏障证明用地/POI 分支确实并发启动。
- 候选发现/API/运行时/Workbench 组合定向回归 `26 passed in 3.72s`；完整回归 `523 passed in 11.65s`。
- 下一阶段是 Supervisor Graph 与可恢复人工确认中断；ScenarioVersion、ConstraintAgent 和长期记忆仍未实现。

### Supervisor Graph、可恢复候选确认与子图编排

- 新增 `site-selection-supervisor-dag@2026.08-supervisor-v1`，统一编排候选发现、人工确认、正式分析和完成门禁。
- Supervisor 与前两层子图共用 Plan 驱动编译器，五个真实运行节点与审核 Manifest 一一对应。
- `candidate_confirmation` 使用 LangGraph `interrupt()`；未配置 Checkpointer 时拒绝构建，避免不可恢复的人工停点。
- 新增 `SiteSelectionSupervisor.start()/confirm()` 会话门面，拒绝重复 session、未知 session 和错误生命周期恢复。
- 人工确认在 `Command(resume=...)` 前校验候选白名单和用地门禁；非法选择不消费停点，可在同一 session 修正后重试。
- 节点内保留第二次候选校验，防止未来其他调用入口绕过门面。
- 正式分析通过应用 Adapter 复用候选发现的 POI 证据快照；发现只执行一次，确认后不重新加载整批在线 POI。
- 修复 Checkpointer 序列化边界：候选发现图状态不再保存 `SiteSelectionRuntime` 或 Profile；Runtime、Gateway 和连接对象由节点按稳定业务 ID 重新解析。
- 明确 `InMemorySaver` 仅用于测试；FastAPI/RQ/Workbench 与 Redis/Postgres 持久化 Checkpointer 尚未装配。
- 新增 Supervisor 暂停/恢复、防篡改、同停点重试、快照复用、Plan 一致性和会话生命周期测试。
- Supervisor/图编译/候选发现组合定向回归 `26 passed in 3.31s`；完整回归 `528 passed in 11.37s`。
- 更新 Agent 手册、架构与候选发现文档，补充核心代码、检查点状态边界、记忆分层、性能影响、面试表达和生产化顺序。

### Supervisor 持久化接入、并发确认与页面恢复

- Supervisor Run 新增 `checkpoint_id`，`start/get/confirm` 统一从当前 StateSnapshot 构造响应。
- `confirm` 要求 `expected_checkpoint_id`，陈旧页面或重复提交在恢复前返回版本冲突。
- 新增 `RedisSupervisorSessionCoordinator`，管理 session TTL、`SET NX EX` 确认锁、token Lua 释放和审计事件。
- 新增应用服务层，生成 session ID、使用服务端 UTC 确认时间、记录五类事件，并在租约过期访问时删除 checkpoint thread。
- Compose API 装配官方 `langgraph-checkpoint-postgres`；启动时执行 `PostgresSaver.setup()`，初始化失败时关闭失败，不回退内存。
- 新增 Supervisor start/get/confirm/events API，分别映射 404、业务阻断 409、版本/锁冲突 409、未配置 503 和脱敏 500。
- Workbench 自动发现改走 Supervisor；session ID 写入 URL，可刷新或手工恢复。
- 自动发现候选表改为勾选模式，ID、坐标、面积和空间数据集冻结；服务端只接受候选 ID 并从 checkpoint 恢复原始几何。
- Supervisor 完成结果复用现有候选对比、地图、POI、Agent Trace 和证据视图；原 `/runs` 异步报告链继续服务其他入口。
- 新增 Redis 协调器、持久化装配、API 生命周期、陈旧 checkpoint、审计事件、Workbench Client 和结果适配测试。
- 组合定向回归 `33 passed in 4.11s`；全量回归 `536 passed in 12.92s`。
- 因本机新增依赖下载审批返回 403，未执行真实 PostgresSaver Docker 构建和 API 重启恢复 Smoke；文档明确保留该验证边界。

### Supervisor 两阶段重启 Smoke 契约与最终回归

- 新增 `scripts/smoke_supervisor_runtime.py`，把验证拆成 `start` 与 `resume` 两阶段，允许在中间真实重启 API。
- Start 阶段冻结 session、checkpoint 与候选 ID；Resume 阶段校验 checkpoint 不漂移、非法候选返回 409、合法确认完成正式分析。
- Smoke 最终要求审计事件严格为 `started -> awaiting_confirmation -> confirmation_rejected -> confirmed -> completed`。
- 新增脚本契约测试和启动失败补偿清理测试；Supervisor 持久化/API/Workbench/Smoke 组合定向回归 `36 passed in 3.93s`，完整回归 `539 passed in 11.93s`。
- 当前环境仍未真实安装新增 PostgresSaver 依赖并重建容器；覆盖主仓库后需按交付说明执行真实两阶段 Smoke。

### Supervisor 真实 Docker 重启恢复验证

- Docker 冷构建成功安装 `langgraph-checkpoint-postgres 3.1.2`，API、Worker、MCP、Workbench、PostGIS、Redis 六服务全部健康。
- Start 阶段创建 `supervisor-2c019a71-7365-4c2f-a4a9-7b9912d532fc` 并将状态写入 `artifacts/supervisor-smoke-state.json`。
- 仅重启 API 后，Resume 阶段恢复同一 session 与 checkpoint，完成 2 个候选正式分析。
- 审计事件链完整为 `started -> awaiting_confirmation -> confirmation_rejected -> confirmed -> completed`，共 5 段。
- 基础单 API 实例跨进程恢复已验证；多 API 竞争、session 过期竞态、数据库故障切换、Janitor 和认证绑定仍是下一阶段。

### Supervisor 与 RQ 的事件驱动异步边界

- Supervisor Plan 升级为 `2026.08-supervisor-v2`，使用 `analysis_submitted -> analysis_wait -> analysis_completed` 替换同步正式分析节点。
- 人工确认与分析完成分别由两个 LangGraph interrupt 表达；queued 只返回 `202 awaiting_analysis`，不会冒充 completed。
- 复用现有 Redis RunState、RQ Queue、Worker、报告和解释链，没有创建第二套任务系统。
- RunState 与 Queue payload 保存 `supervisor_session_id`；Supervisor checkpoint 保存 `analysis_run_id`，两套状态机通过稳定 ID 关联。
- 新增共享 Supervisor service 工厂，FastAPI 与 Worker 使用同一 Plan、Handler 和 Checkpointer 装配，避免跨进程拓扑漂移。
- Worker 在 completed/failed/cancelled/timed_out 后恢复 Supervisor；恢复失败不改写权威 RunState，后续 GET 以幂等 reconciliation 补偿。
- Redis 确认锁升级为通用 transition lock，同时保护人工确认与分析终态恢复；重复 Worker/GET 完成不会重复推进或重复审计。
- Supervisor 响应新增 `analysis_run_id`、`analysis_run_status` 和 `analysis_error_type`；成功审计链升级为七段，异常终态分别保留失败、取消和超时。
- Workbench 确认后每 2 秒轮询 Supervisor，终态再读取原 RQ Run，因此自动发现路径也保留 LLM 解释、DOCX、Agent Trace 和报告下载；重复轮询不会重置候选编辑器。
- Compose Worker 同步启用 Supervisor/PostgresSaver 的 session 与 lock 配置。
- 更新 README、架构、候选发现、数据字典、性能、Bad Case 和 Agent 实现手册，补充核心代码、记忆/缓存分层、性能语义、项目价值与面试表达。
- 聚焦回归 `40 passed in 3.92s`；补齐异常终态 API 幂等测试后，配置测试解释器的 pywin32 路径，全量回归 `548 passed in 12.50s`。
- 本轮尚未覆盖到主仓库和重建 Docker；覆盖后需真实验证 Worker 驱动七段事件链以及 API/Worker 分别重启。

### POI 在线恢复与 Workbench 证据口径修正

- 真实会话复盘确认评分缓冲区快照 87 条、搜索边界内 15 条，且 7 个批次全部从 OSM 降级到 Fixture；不再把两个空间口径混为“POI 丢失”。
- Overpass 新增单批最多 3 类的能力预算，候选发现按 Profile 评分组和背景小批次执行，避免一次超大多类别查询。
- Fixture 降级结果不再写入在线 Redis 缓存；Provider cache token 进入作用域，上游恢复或配置升级后可获得新在线数据。
- 新增 `SITE_SELECTION_POI_PROXY_URL` 与 `SITE_SELECTION_OVERPASS_MAX_CATEGORIES_PER_QUERY`，API/Worker Compose 配置一致。
- 候选来源摘要新增可选 `fallback_reason`，新任务展示网络、限流或熔断原因，旧 Supervisor checkpoint 仍可恢复。
- Workbench 分开显示边界内 POI、真实在线 POI、Fixture 批次和评分缓冲区 POI；详细警告折叠展示。
- 场景确认上移到版本摘要后，候选确认上移到候选表与 POI 地图之间；地图候选使用短排名标签，避免长编号重叠。
- Agent 实现手册新增故障链、缓存语义、容器代理、证据口径和交互门禁讲解。

### 候选点 POI 自适应补采与侧栏使用引导

- 复盘确认区域级宽域查询达到 Provider 上限时，边缘候选的局部 POI 稀疏不能直接解释为真实市场空白。
- `SnapshotReusingPOIGateway` 改为完整组本地裁剪，截断、缺组或缺类别时按候选中心、Profile 半径、类别和 limit 补查。
- 补查继续复用运行时 Redis 缓存、限流、超时、重试/熔断、PostGIS 持久化和 Fixture 显式降级，不建立第二套 Provider。
- 补查失败且已有局部快照时保留不完整证据并记录错误；完全缺组且补查失败时关闭失败。
- `POISourceMeta` 新增补查状态、原因和错误字段，区分快照复用与候选点新查询，并兼容旧来源 JSON 和旧快照摘要。
- Workbench 标题下提示左上角 `»` 可展开项目类型、候选来源与发现范围设置；正式分析前说明补查规则。
- 正式结果 POI 页签展示补查批次数、失败警告和逐候选/评分组来源明细。
- README、架构、性能、Bad Case、数据字典、Fixture 边界、候选发现文档和 Agent 实现手册同步更新。
- 新增完整/截断/缺组/缺类别/失败回退/旧摘要兼容和 Run 级补查测试；全量回归 `566 passed in 13.01s`。
- 独立 Workbench 在 1280×720 与 390×844 视口验证设置提示，无 Traceback 和横向溢出。

### 候选发现 POI 分区修复与可信第一次排名

- 复盘真实 Supervisor 会话：1,648 条评分快照和 652 条边界内真实 POI 仍掩盖严重类别失衡；交通、办公、居住和停留环境降级 Fixture，互补商业返回 1,000/1,260 条且截断，候选局部多组为零。
- 在 `poi_market_evidence` 内增加完整性驱动的 2x2 分区修复；触发条件为在线降级、截断或缺少 Profile 类别，覆盖整个候选范围而不是只补当前前 8 名。
- 分区结果只接受真实在线来源，按 POI ID 合并去重并重算宽域距离；部分成功继续标记不完整，全部失败保留原降级证据和异常摘要。
- 修复后的六组证据用于第一次评分、范围地图和 Redis 快照；正式分析的候选点按需补采仍保留，形成候选池公平修复与局部精查两层策略。
- `CandidateDiscoverySource/Report` 新增完整性、补查请求/成功、新增记录和剩余缺口字段；Workbench 增加四项修复指标和逐组来源审计。
- Compose 与 Provider 默认连续失败阈值从 1 调整为 6，避免单个宽域失败立即阻断其余五个评分组；补查每组固定 4 请求并进入同一个最多 4 Worker 的交错队列，继续使用共享限速、缓存和熔断。
- 用地门禁不变：市场探索即使 POI 修复成功仍保持 `formal_analysis_allowed=false`。
- 专项回归 `42 passed`，全量回归 `573 passed in 13.80s`；Workbench 在 1280×720 和 390×844 下无横向溢出或控制台错误。

### 候选发现超时修复与全局补查调度

- 复现 Workbench “选址 API 调用超时”：六个评分组原先逐组执行 2x2 补查，单请求 8 秒边界下理论等待可超过默认 90 秒客户端超时。
- 把全部不完整组的最多 24 个查询汇总到一个全局 4 Worker 执行器，并按分区与评分组交错，避免慢组独占队列；查询预算、真实来源过滤、评分和用地门禁不变。
- Provider 的 2 次/秒共享限速、Redis 缓存、熔断和单请求超时继续生效；提高 Worker 数不等于放宽上游请求速率。
- Workbench 仅为 Supervisor start 提供至少 150 秒的有界客户端保护，其他 API 默认仍为 90 秒；Spinner 与超时错误明确说明首次在线补查可能等待及缓存复用语义。
- 新增跨评分组单批次交错、请求级超时和专用错误信息测试；候选发现与 Workbench 定向回归 `32 passed in 3.30s`，全量回归 `576 passed in 18.56s`。

### 任意区域市场探索与显式全流程演示

- 复盘新 Supervisor 会话：徐汇区 4 km 范围加载 4,995 条边界 POI、冻结 6,304 条评分快照，候选发现耗时 32.65 秒；阻断原因不是 POI 太少，而是范围与内置咖啡店机会单元完全不相交，策略按设计降级为 `market_exploration`。
- 保留用地硬门禁，不允许把 `MARKET-*` 网格或 POI 热点自动冒充可用地块。
- `FixtureCandidateCatalog` 新增零售演示范围推导，从版本化候选中心加固定边距，不在 Workbench 散落两套坐标常量。
- Workbench 的发现范围和用地阻断结果区新增显式演示入口；用户主动触发后使用 `strict` 模式创建新 Supervisor session，旧会话保持不可变。
- 命中演示机会单元时页面展示数据集 ID 与合成用地警告，说明只验证候选发现、人工确认、GIS/规则、异步分析和报告链，不代表真实许可。
- 真实 API 验证咖啡店演示范围返回 `registered_land`、8 个候选、评估 20 个机会单元、用地排除 5 个，数据集 `demo-coffee-discovery-pool@fixture-rich-v1`，`formal_analysis_allowed=true`，发现耗时 33.79 秒。
- 目录、候选发现和 Workbench 组合回归 `38 passed in 3.05s`，全量回归 `577 passed in 13.86s`；独立页面验证就地入口、新 session、合成警告和正式分析按钮启用，`390×844` 手机视口无横向溢出。
- 浏览器日志发现并修复 Streamlit Widget 默认值与演示回调 Session State 的双重所有权告警；候选来源、数量和间距改为仅在 key 缺失时初始化。
- 状态所有权修复后组合回归 `38 passed in 3.15s`，全量回归 `577 passed in 14.62s`。
- Workbench 中 26 处已弃用的 `use_container_width=True` 统一迁移为 `width="stretch"`，源码测试防止旧参数回归。
- 最终全量回归 `577 passed in 13.93s`；页面重载后终端无 Session State 或 `use_container_width` 警告。

### 商业选址与用地合规双分析范围

- 修正 `formal_analysis_allowed` 同时阻断商业分析和合规结论的过粗门禁；字段继续表示完整 GIS/政策合规能力，不再控制全部零售分析。
- 新增 `AnalysisScope.MARKET_SELECTION/FULL_COMPLIANCE`，并贯穿 ProjectRequest、API/RQ 命令、RunState、Worker 结果、响应和报告。
- Supervisor 对无可核验用地的咖啡店/便利店候选自动选择市场分析；候选白名单、checkpoint、快照一致性和非零售用地门禁保持不变。
- 市场分支继续按候选和 Profile 半径复用 POI 快照、补采缺失类别、执行版本化 POI 评分和排名；GIS 与政策节点显式记录 `skipped`，证据状态为 `NOT_RUN`。
- Evidence Review 新增 `land_compliance_unverified` warning；POI 缺失仍为 blocker，不因市场 Scope 放松证据完整性。
- Workbench 启用“确认候选并运行商业选址分析”，原红色阻断改为待核验警告；演示用地入口移入开发选项。
- DOCX 市场报告使用独立标题、分析范围元数据和待核验 GIS/政策段落，不把空规则结果写成“未命中即合规”。
- 更新 README、架构、候选发现、零售能力、数据字典、Bad Case 与 Agent 实现手册，记录核心代码、缓存/快照、性能和面试表达。
- 本轮工作流、Supervisor、API、报告和 Workbench 组合回归 `74 passed`；本机扩展回归 `573 passed, 4 deselected`，未执行项均依赖当前测试解释器缺少的 Windows `pywintypes`。
