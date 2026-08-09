# AI Agent Learning

用于记录 Python、Git、FastAPI、Agent、RAG 和 LLM 应用开发的学习过程与代码实践。

当前项目已经完成 Python 图层统计练习和 FastAPI 接口骨架。FastAPI 部分目前是桩接口，用于练习接口设计、参数校验、Swagger 联调和自动化测试，尚未接入真实 LLM、RAG、数据库或 GIS 分析。

## 当前功能

- Python 图层数据读取与统计
- JSON 文件解析与异常处理
- `GET /health` 健康检查接口
- `POST /documents` 文档元数据接收接口
- `POST /chat` 选址问题接收桩接口
- Pydantic 请求与响应模型
- Swagger 接口调试页面
- pytest 和 unittest 自动化测试

## 环境要求

- Windows 10 或 Windows 11
- PowerShell
- Python 3.12（当前验证版本：Python 3.12.4）
- Git

## 项目结构

```text
ai-agent-learning/
├─ app/
│  ├─ main.py
│  ├─ api/
│  │  ├─ health.py
│  │  ├─ documents.py
│  │  └─ chat.py
│  ├─ schemas/
│  │  ├─ documents.py
│  │  └─ chat.py
│  └─ services/
│     ├─ document_service.py
│     └─ chat_service.py
├─ practice/
│  ├─ data/
│  ├─ layer_stats/
│  ├─ python_basics.py
│  └─ run_layer_stats.py
├─ tests/
│  ├─ test_api.py
│  └─ test_layer_stats.py
├─ notes/
├─ requirements.txt
├─ progress.md
└─ README.md
```

## 创建虚拟环境

进入项目目录：

```powershell
Set-Location -LiteralPath path\to\ai-agent-learning
```

首次使用时创建虚拟环境：

```powershell
python -m venv .venv
```

如果 PowerShell 禁止执行激活脚本，只对当前终端临时放行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

验证 Python：

```powershell
python --version
```

## 安装依赖

```powershell
python -m pip install -r requirements.txt
```

当前主要依赖：

- `fastapi`：定义 Web API
- `uvicorn`：启动本地 ASGI 服务
- `pytest`：运行自动化测试
- `httpx`：支持 FastAPI 测试客户端发送请求

## 启动 FastAPI

在项目根目录执行：

```powershell
python -m uvicorn app.main:app --reload
```

启动成功后访问：

- Swagger：<http://127.0.0.1:8000/docs>
- OpenAPI：<http://127.0.0.1:8000/openapi.json>
- 健康检查：<http://127.0.0.1:8000/health>

`--reload` 仅用于本地开发。保存 Python 文件后，Uvicorn 会自动重新加载应用。

## API 接口

| 方法 | 路径 | 作用 | 成功状态码 |
|---|---|---|---|
| GET | `/health` | 返回服务状态和版本 | `200` |
| POST | `/documents` | 接收文件名、来源和文档类型 | `201` |
| POST | `/chat` | 接收问题、项目类型和候选地块 | `200` |

`/chat` 当前只允许以下项目类型：

```text
shopping_mall
logistics_park
```

当前 `/documents` 和 `/chat` 均为桩接口，不会保存文件，也不会执行真实 Agent 或选址合规分析。

## 运行自动化测试

运行全部测试：

```powershell
python -m pytest -v
```

简洁输出：

```powershell
python -m pytest -q
```

当前测试覆盖：

- 健康检查正常请求
- 文档接口正常请求和缺失字段
- Chat 接口正常请求、空问题和非法项目类型
- 图层统计正常数据、空列表、重复图层和异常 JSON 等场景

最近一次验证结果：

```text
12 passed, 1 warning
```

warning 来自 FastAPI/Starlette 测试客户端的依赖弃用提示，不影响当前测试结论。

## 运行图层统计练习

```powershell
python -m practice.run_layer_stats
```

该程序读取 `practice/data/layers.json`，输出图层总数、图层类型、缺少 CRS 的图层和分类统计。

## 当前阶段

已完成：

- Python 模块、类、异常处理和 JSON 读取
- Git 分支、合并、冲突处理和 GitHub 推送
- FastAPI 三个基础接口
- Pydantic 参数校验
- Swagger 手工联调
- 12 项自动化测试

后续计划：

- 将文档接口接入真实文件处理流程
- 为 Chat 接口增加意图识别和结构化参数抽取
- 接入 RAG、GIS 工具和可追溯的合规分析结果
- 增加日志、配置管理和更完整的接口测试
