# 学习进度

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
