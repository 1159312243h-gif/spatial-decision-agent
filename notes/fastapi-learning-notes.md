# FastAPI 入门与项目结构学习笔记

## 1. 当前学习目标

本阶段要为“建设项目选址与国土空间合规决策 Agent”建立一个最小后端接口，使其他程序或网页以后可以通过统一方式调用 Agent 能力。

当前计划实现三个接口：

| 请求方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | 检查后端服务是否正常运行 |
| POST | `/documents` | 接收待处理文档的元数据 |
| POST | `/chat` | 接收用户问题、项目类型和候选地块信息 |

今天只实现接口骨架、数据校验和测试，不接入真实 LLM、RAG、数据库或 GIS 计算。

## 2. FastAPI 是什么

FastAPI 是一个使用 Python 开发 Web API 的框架。

普通 Python 函数只能被当前 Python 程序直接调用。使用 FastAPI 后，可以给函数分配一个网络访问地址，让浏览器、前端网页、其他后端服务或测试程序通过 HTTP 请求调用它。

例如，普通函数可能是：

```python
def get_health() -> dict[str, str]:
    return {"status": "ok"}
```

加上 FastAPI 路由后：

```python
@router.get("/health")
def get_health() -> dict[str, str]:
    return {"status": "ok"}
```

它就可以通过下面的地址访问：

```text
http://127.0.0.1:8000/health
```

FastAPI 在当前项目中的主要作用是：

1. 接收外部请求，例如问题、项目类型和候选地块。
2. 使用 Pydantic 检查请求数据是否合法。
3. 调用 Python 服务函数处理业务。
4. 把处理结果转换成 JSON 并返回。
5. 自动生成 OpenAPI 接口说明和 Swagger 调试页面。

## 3. 什么是 API

API 是不同程序之间约定好的调用方式。

可以把它理解为餐厅的点餐窗口：

```text
用户或前端       提交请求
     ↓
API 接口         检查请求格式并转交任务
     ↓
业务服务         执行实际处理
     ↓
API 接口         返回处理结果
```

例如，`POST /documents` 约定调用者需要提交：

```json
{
  "filename": "land_policy.pdf",
  "source": "自然资源部门",
  "document_type": "planning_policy"
}
```

调用者不需要知道后端内部如何组织文件，只需要遵守接口约定。

## 4. Uvicorn 是什么

FastAPI 负责定义接口和处理逻辑，Uvicorn 负责真正启动网络服务并监听请求。

启动命令：

```powershell
python -m uvicorn app.main:app --reload
```

`app.main:app` 的含义：

| 部分 | 含义 |
|---|---|
| 第一个 `app` | 项目中的 `app/` Python 包 |
| `main` | `app/main.py` 模块 |
| 最后一个 `app` | `main.py` 中创建的 FastAPI 对象 |

`--reload` 表示开发时监视代码变化。保存 Python 文件后，Uvicorn 会自动重新加载应用。它适合本地开发，不是正式生产环境的完整部署方案。

## 5. `127.0.0.1:8000` 是什么

```text
http://127.0.0.1:8000
```

各部分含义：

| 部分 | 含义 |
|---|---|
| `http://` | 使用 HTTP 协议通信 |
| `127.0.0.1` | 当前这台电脑，也叫 localhost |
| `8000` | Uvicorn 当前监听的端口 |
| `/health` | 健康检查接口路径 |
| `/docs` | Swagger 接口文档路径 |

这个地址不是发布到互联网的网站。它只能在本机服务运行期间访问。关闭 Uvicorn 后，浏览器就无法继续访问该地址。

## 6. Swagger 是什么

Swagger UI 是 FastAPI 根据代码自动生成的接口说明和调试网页，默认地址是：

```text
http://127.0.0.1:8000/docs
```

这个网页不是项目最终要交付给普通用户的业务页面。它主要提供给开发人员、测试人员和前后端联调人员使用。

Swagger 可以用来：

1. 查看当前服务有哪些接口。
2. 查看每个接口使用 GET 还是 POST。
3. 查看请求必须包含哪些字段。
4. 查看字段类型、说明和示例。
5. 点击 `Try it out` 直接发送请求。
6. 查看响应状态码、响应体和响应头。
7. 检查 Pydantic 参数校验是否生效。

Swagger 的接口信息来自 FastAPI 自动生成的 OpenAPI 描述。修改路由、Pydantic 模型或响应模型后，Swagger 页面也会随之变化。

### Swagger 与 Agent 参数解析的区别

Swagger 不负责让 Agent 从自然语言中抽取参数。它展示的是开发者已经定义好的 API 契约，并允许开发者手动填写结构化 JSON 来测试接口。

例如，在 Swagger 中调用 `/chat` 时，填写的数据已经被人工拆成：

```json
{
  "question": "请比较两个候选地块",
  "project_type": "logistics_park",
  "candidate_parcels": []
}
```

这里：

- Swagger 负责展示字段和发送请求。
- Pydantic 负责检查字段是否存在、类型是否正确、取值是否合法。
- 当前桩 Service 负责返回固定格式的测试响应。
- 当前还没有 LLM 或 Agent 负责理解原始自然语言并自动生成这些字段。

未来接入 Agent 后，完整流程可以是：

```text
用户输入自然语言命令
        ↓
LLM 或意图识别模块抽取结构化参数
        ↓
调用 FastAPI /chat 接口
        ↓
Pydantic 校验参数
        ↓
Service 调用 Agent、RAG 或 GIS 工具
        ↓
返回分析结果
```

因此，Swagger 当前证明的是“接口能够接收和校验结构化参数”，而不是“Agent 已经能够把自然语言拆成参数”。

## 7. GET 和 POST 的区别

### GET

GET 通常用于读取信息，一般不改变服务中的数据。

当前示例：

```text
GET /health
```

它只是询问服务是否正常运行。

### POST

POST 通常用于向服务提交数据，让服务创建记录或执行处理。

当前示例：

```text
POST /documents
POST /chat
```

这两个接口都需要在请求体中发送 JSON 数据。

## 8. Pydantic 是什么

Pydantic 用 Python 类型声明描述请求和响应的数据结构，并在程序运行时自动校验数据。

例如：

```python
class DocumentCreate(BaseModel):
    filename: str
    source: str
    document_type: str
```

这表示请求必须包含三个字符串字段。如果调用者漏掉 `source`，FastAPI 会在进入业务函数前自动返回 `422`，不需要手动写大量 `if` 判断。

当前项目还使用 `StringConstraints`：

```python
StringConstraints(strip_whitespace=True, min_length=1)
```

作用是：

- `strip_whitespace=True`：去掉字符串首尾空格。
- `min_length=1`：去掉空格后至少保留一个字符。
- 空字符串或只有空格的字符串不能通过校验。

## 9. 常见 HTTP 状态码

| 状态码 | 含义 | 当前项目中的场景 |
|---|---|---|
| `200` | 请求成功 | `GET /health` 成功 |
| `201` | 创建或接收成功 | `POST /documents` 成功接收文档元数据 |
| `422` | 请求格式或字段校验失败 | 缺少字段、字段类型错误、字符串为空 |
| `500` | 服务内部出现未处理错误 | Python 代码异常或服务逻辑失败 |

## 10. 当前请求处理流程

```text
浏览器、Swagger 或其他程序
              ↓ HTTP 请求
Uvicorn 接收请求
              ↓
app/main.py 中的 FastAPI 应用
              ↓
app/api/ 中匹配对应路由
              ↓
app/schemas/ 中的 Pydantic 模型校验数据
              ↓
app/services/ 中的函数处理业务
              ↓
FastAPI 将结果转换为 JSON
              ↓ HTTP 响应
浏览器、Swagger 或其他程序
```

## 11. 项目目录和文件职责

当前目标结构：

```text
ai-agent-learning/
├─ app/
│  ├─ __init__.py
│  ├─ main.py
│  ├─ api/
│  │  ├─ __init__.py
│  │  ├─ health.py
│  │  ├─ documents.py
│  │  └─ chat.py
│  ├─ schemas/
│  │  ├─ __init__.py
│  │  ├─ documents.py
│  │  └─ chat.py
│  └─ services/
│     ├─ __init__.py
│     ├─ document_service.py
│     └─ chat_service.py
├─ tests/
│  └─ test_api.py
├─ requirements.txt
├─ README.md
└─ progress.md
```

### `requirements.txt`

记录项目需要安装的第三方依赖：

```text
fastapi
uvicorn
pytest
httpx
```

- `fastapi`：定义 API。
- `uvicorn`：启动本地 Web 服务。
- `pytest`：运行自动化测试。
- `httpx`：测试代码向 FastAPI 应用发送模拟 HTTP 请求。

### `app/__init__.py`

标记 `app/` 是 Python 包，使代码可以使用 `from app...` 导入模块。当前可以保持为空。

### `app/main.py`

应用入口，负责：

1. 创建 `FastAPI` 对象。
2. 设置应用名称和版本。
3. 将各个路由注册到应用。

它不应该堆放所有参数模型和业务逻辑，否则项目扩大后会难以维护。

### `app/api/`

API 层负责 HTTP 相关工作：

- 定义请求方法和路径。
- 接收请求参数。
- 指定响应模型和状态码。
- 调用 `services/` 中的业务函数。

`app/api/health.py` 定义 `GET /health`。

`app/api/documents.py` 应当定义 `POST /documents`。

以后 `app/api/chat.py` 定义 `POST /chat`。

### `app/schemas/`

Schema 层负责定义输入和输出的数据形状以及校验规则。

`app/schemas/documents.py` 应当包含：

- `DocumentCreate`：文档接口的请求模型。
- `DocumentResponse`：文档接口的响应模型。

以后 `app/schemas/chat.py` 包含聊天接口的请求和响应模型。

### `app/services/`

Service 层负责业务逻辑，不直接关心 Swagger 页面或 HTTP 请求细节。

`app/services/document_service.py` 当前只生成 UUID 并返回文档元数据，是一个桩服务。以后可以替换为文件解析、数据库写入或向量化处理。

以后 `app/services/chat_service.py` 可以负责调用 Agent、RAG 或 GIS 工具。

### `tests/`

存放自动化测试。`tests/test_api.py` 将通过 FastAPI 的 `TestClient` 测试正常请求和异常请求，避免每次都依赖人工点击 Swagger。

### `README.md`

面向项目使用者，记录安装、启动、接口和测试命令。

### `progress.md`

面向学习过程，记录当天完成内容、遇到的问题、解决方式和下一步任务。

## 12. 已完成并验证的内容

### 依赖安装

已在 Python 3.12.4 虚拟环境中成功导入：

```text
FastAPI 0.141.1
Uvicorn 0.52.1
pytest 9.1.1
httpx 0.28.1
```

### `GET /health`

已通过 Swagger 验证：

```text
HTTP 状态码：200
```

响应体：

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

这说明 Uvicorn、FastAPI 应用、路由注册和 JSON 响应均正常工作。

### `POST /documents` 路由注册

修正 `app/api/documents.py` 与 `app/schemas/documents.py` 后，Swagger 页面已正常恢复，并同时显示：

```text
GET  /health
POST /documents
```

这说明 `/documents` 已成功注册到 FastAPI 应用，OpenAPI 能够读取其请求模型和响应模型。

随后已通过 Swagger 完成接口测试：

- 使用完整的文档元数据发送请求，接口成功返回 `201`。
- 响应包含自动生成的 `document_id`、`accepted` 状态和原始元数据。
- 删除必填字段后，Pydantic 成功返回 `422`。

因此，`POST /documents` 的桩接口、响应模型和缺失字段校验已经通过当前阶段验收。

### `POST /chat` 路由注册

完成 Chat Schema、Service、API 路由和主应用注册后，通过 OpenAPI 路径检查得到：

```text
['/health', '/documents', '/chat']
```

这说明三个接口均已注册到 FastAPI 应用。

随后已通过 Swagger 完成三项测试：

- 正常问题、合法项目类型和两个候选地块返回 `200`。
- 响应状态为 `stub`，`received_candidates` 为 `2`。
- 只有空格的问题被 Pydantic 拦截并返回 `422`。
- 不在允许范围内的项目类型被 Pydantic 拦截并返回 `422`。

因此，`POST /chat` 桩接口和本阶段要求的参数校验已通过手工验收。

### pytest 自动化测试

已创建 `tests/test_api.py`，使用 FastAPI `TestClient` 自动检查：

1. `/health` 正常返回。
2. `/documents` 正常接收文档元数据。
3. `/documents` 缺少必填字段时返回 `422`。
4. `/chat` 正常返回桩响应。
5. `/chat` 拒绝空问题。
6. `/chat` 拒绝非法项目类型。

运行命令：

```powershell
python -m pytest -v
```

实际结果：

```text
collected 12 items
12 passed, 1 warning
```

其中 6 项是新增 API 测试，另外 6 项是原有图层统计测试。`TestClient` 直接在测试进程中调用 FastAPI 应用，不要求 Uvicorn 或浏览器正在运行。

当前 warning 来自 FastAPI/Starlette 测试客户端对 `httpx` 依赖方式的弃用提示，不影响本次测试结论。暂不为消除 warning 贸然更换依赖，后续结合官方兼容说明统一处理。

## 13. 问题与修复记录

### 13.1 `documents.py` 内容放反

在 2026-08-09 的文件核对中发现：

- `app/schemas/documents.py` 错误地放入了 API 路由代码。
- `app/api/documents.py` 错误地放入了 Pydantic 模型代码。
- `app/main.py` 从 `app.api.documents` 导入 `router` 时会失败。

注册路由并刷新 `/docs` 后，Swagger 因应用重新加载失败而显示白屏。现已完成修正：

- `app/api/documents.py` 存放 FastAPI 路由。
- `app/schemas/documents.py` 存放 Pydantic 模型。
- `from app.main import app` 已能成功完成应用导入。

排查这类白屏时，应先查看运行 Uvicorn 的终端。浏览器白屏只是表面现象，终端中的 `ImportError`、`SyntaxError` 或其他 traceback 才是定位后端启动失败的主要依据。

### 13.2 路由检查命令不兼容

最初使用下面的命令检查路由：

```powershell
python -c "from app.main import app; print([route.path for route in app.routes])"
```

FastAPI 0.141.1 的 `app.routes` 中包含 `_IncludedRouter` 对象，该对象没有 `path` 属性，因此出现：

```text
AttributeError: '_IncludedRouter' object has no attribute 'path'
```

这个报错来自检查命令本身，不代表应用导入失败。更稳妥的方式是通过 FastAPI 生成的 OpenAPI 文档查看公开接口路径：

```powershell
python -c "from app.main import app; print(list(app.openapi()['paths']))"
```

预期至少包含 `/health` 和 `/documents`。

修正检查命令后，应用路径和 Swagger 页面均已恢复正常。

## 14. 下一步验收

修复文件位置后，在 Swagger 中完成：

1. 使用完整 JSON 调用 `POST /documents`，预期返回 `201`。
2. 删除 `source` 字段再次调用，预期返回 `422`。
3. 输入空字符串，确认 Pydantic 校验是否生效。
4. 记录实际结果后，再把 `/documents` 标记为已完成。

## 15. 更新记录

### 2026-08-09

- 创建本笔记。
- 记录 FastAPI、API、Uvicorn、Swagger、Pydantic 和 HTTP 状态码。
- 记录当前项目目录及文件职责。
- 记录 `/health` 的实际 Swagger 验证结果。
- 发现并记录 `documents.py` 两个文件内容互换的问题。
- 注册文档路由后出现 Swagger 白屏；确认根因是文件内容仍未交换，导致应用导入失败。
- 修正 `documents.py` 文件位置，确认 FastAPI 应用可以导入。
- 记录 `_IncludedRouter` 导致旧路由检查命令报错，并改用 OpenAPI 路径检查。
- Swagger 页面恢复正常，确认 `/health` 和 `/documents` 均已注册。
- `/documents` 正常请求返回 `201`，缺失字段请求返回 `422`，完成当前阶段验收。
- OpenAPI 路径检查包含 `/health`、`/documents` 和 `/chat`，确认 Chat 路由注册成功。
- `/chat` 正常请求、空问题和非法项目类型测试均符合预期，完成手工 Swagger 验收。
- 新增 6 个 API 自动化测试；连同原有测试共 12 项全部通过。最近一次 `pytest -q` 用时 0.29 秒。
- 记录 TestClient 的依赖弃用 warning，当前不影响验收。
- 补充 Swagger、Pydantic 与未来 Agent 自然语言参数抽取之间的职责区别。
