# 2026-08-11 LLM 聊天与 Prompt 学习笔记

## 今日知识卡

### 知识卡 1：Token

#### 一句话理解

Token 是大模型读取和生成文本时使用的基本单位，不一定等于一个汉字、一个英文单词或一个字符。

#### 需要记住

- 中文可能按单个汉字、词组或标点拆分，具体结果取决于模型使用的分词器。
- 英文单词可能是一个 Token，也可能被拆成多个 Token。
- 系统指令、历史对话、当前问题和模型回答都会消耗 Token。
- Token 数量会影响上下文容量、响应速度和 API 调用成本。
- 内容越长不一定越好，无关信息会占用上下文并干扰模型判断。

#### 当前项目中的例子

调用模型时，下列内容都会占用 Token：

```python
response = client.responses.create(
    model=model_name,
    instructions=system_message,
    input=model_input,
)
```

- `instructions`：选址合规审查助手的身份和规则。
- `input`：用户当前问题，以及滑动窗口保留的历史对话。
- 模型生成的 `response.output_text`：输出 Token。

#### 常见误区

- 错误：一个汉字一定等于一个 Token。
- 正确：Token 如何划分由模型的分词器决定。
- 错误：只有模型的回答才消耗 Token。
- 正确：输入和输出通常都会计入 Token 使用量。

#### 自测题

问：为什么不能无限保留所有历史对话？

答：历史对话会持续占用 Token，可能超过上下文窗口，也会增加调用成本和无关信息干扰。

---

### 知识卡 2：上下文窗口

#### 一句话理解

上下文窗口是模型在一次请求中能够读取和处理的 Token 总量范围。

#### 需要记住

- 上下文通常包含系统指令、历史消息、当前输入，以及需要为模型输出预留的空间。
- 上下文窗口有长度上限，并不等于永久记忆。
- 超出限制时，可以删除旧消息、保留最近消息，或者先总结旧消息再保留摘要。
- 重要规则应放在系统指令中，不应随着普通历史消息一起被淘汰。
- 保留对话时应以完整轮次为单位，同时保留对应的 `user` 和 `assistant` 消息。

#### 当前项目中的例子

项目中的 `ConversationContext(max_rounds=2)` 只保留最近两轮完整对话：

```text
第 1 轮：user 问题1 + assistant 回答1
第 2 轮：user 问题2 + assistant 回答2
第 3 轮：user 问题3 + assistant 回答3
```

加入第 3 轮后，第 1 轮被删除，保留第 2、3 轮。下一次提问时，再在末尾加入当前 `user` 消息。

系统指令通过 Responses API 的 `instructions` 单独传入，因此不会被滑动窗口删除。

#### 为什么要保留完整轮次

如果只保留用户问题、不保留模型回答，后续模型无法知道之前给过什么答复；如果只保留回答、不保留问题，回答会失去来源。完整的问答轮次才能维持连贯语义。

#### 常见误区

- 错误：上下文窗口就是模型永久保存的记忆。
- 正确：它只是当前一次请求能看到的内容范围。
- 错误：只要模型支持很长的上下文，就应该把所有资料全部传入。
- 正确：仍然需要筛选相关内容，减少噪声和 Token 消耗。

#### 自测题

问：为什么系统消息不应该放入会自动淘汰的滑动窗口？

答：系统消息规定模型身份、任务边界和安全规则。一旦被淘汰，后续回答可能偏离任务要求。

---

### 知识卡 3：消息角色

#### 一句话理解

消息角色用来告诉模型每段内容是谁提供的，以及这段内容在对话中承担什么作用。

#### 三种常见角色

| 角色 | 主要作用 | 当前项目示例 |
|---|---|---|
| `system` | 规定身份、目标、约束和行为边界 | 不编造审查结果，不代替法定审批结论 |
| `user` | 提供问题、需求、数据和补充信息 | 比较两个物流园候选地块 |
| `assistant` | 保存模型之前的回答，使后续对话连贯 | 已记录候选地块编号 A01 |

#### 当前 Responses API 的对应关系

当前项目使用 Responses API，不是 Chat Completions API：

| 对话概念 | 当前项目中的参数或字段 |
|---|---|
| 系统指令 | `instructions=system_message` |
| 当前输入或历史消息 | `input=model_input` |
| 模型回答 | `response.output_text` |

当使用滑动窗口时，`input` 可以是包含 `user` 和 `assistant` 角色的消息列表。

#### 项目中的职责边界

```text
system：你是建设项目选址合规审查助手，不编造数据，不直接作出法定结论。
user：请比较 A01 和 B01 两个候选地块。
assistant：先核实位置、范围、坐标和规划管控数据，再执行比较。
```

系统指令用于稳定模型行为，但不能代替程序校验、GIS 计算、规则引擎或真实数据。

#### 常见误区

- 错误：把任务规则、用户数据和历史回答全部拼成一大段普通文本，角色无所谓。
- 正确：区分角色能让模型更清楚地理解规则、问题和历史回答之间的关系。
- 错误：有了 `system` 指令，模型就一定不会犯错。
- 正确：系统指令只能约束行为倾向，关键结果仍需代码和数据校验。

#### 自测题

问：“不得编造缺失的地块坐标”应该放在哪个角色中？

答：如果这是整个应用始终有效的规则，应放在 `system` 指令中；某一次任务的地块信息则放在 `user` 输入中。

---

### 知识卡 4：Temperature

#### 一句话理解

Temperature 是控制模型输出随机性和多样性的常见参数；值越低通常越稳定，值越高通常越发散。

#### 需要记住

- 低 Temperature 适合字段提取、分类、结构化输出和合规审查说明。
- 高 Temperature 适合头脑风暴、文案创作和需要多样性的任务。
- Temperature 不控制知识是否真实，也不能保证结果正确。
- 同样的 Prompt 在较高 Temperature 下，重复调用时更容易出现不同答案。
- 不同模型和接口对 Temperature 的支持范围可能不同。

#### 当前项目中的使用判断

选址合规项目更看重稳定、可验证和可解析，因此如果接口支持，通常应选择较低的 Temperature。不过，当前公司模型的 Responses 兼容接口是否支持该参数尚未实际验证，不能直接把它写成已完成能力。

验证时应先查接口说明，或者使用非敏感测试请求确认。示意代码如下：

```python
response = client.responses.create(
    model=model_name,
    instructions=system_message,
    input=model_input,
    temperature=0.2,
)
```

只有接口调用成功且输出符合预期后，才能在项目记录中写“已支持并验证 Temperature”。

#### 常见误区

- 错误：Temperature 设为 0，模型回答就一定正确。
- 正确：低值只能降低随机性，不能消除幻觉、错误数据或推理错误。
- 错误：Temperature 越高，模型能力越强。
- 正确：它主要改变输出的随机性和多样性，不代表能力高低。
- 错误：所有兼容 OpenAI 格式的接口都支持相同参数。
- 正确：第三方兼容接口可能只实现部分参数，需要按实际接口验证。

#### 自测题

问：为什么结构化 JSON 输出通常选择较低的 Temperature？

答：较低的随机性有助于模型遵守固定字段和格式，但仍必须使用 Pydantic 等程序化校验处理非法 JSON、缺字段和类型错误。

---

## 四张卡的串联理解

一次模型调用中，`system` 规定行为边界，`user` 提供当前任务，`assistant` 历史回答帮助延续上下文；所有这些文本都会被转换成 Token，并共同占用上下文窗口。滑动窗口负责控制历史消息长度，Temperature 则在接口支持时用于调节输出随机性。

可以用下面这句话闭卷复述：

> 模型按角色读取系统指令、历史对话和当前问题，这些内容都会转换成 Token 并占用上下文窗口；当历史过长时需要滑动或总结，而 Temperature 只调节输出随机性，不能替代事实与格式校验。

## 今日验收清单

- [ ] 能用自己的话解释 Token，而不是把它简单等同于“一个字”。
- [ ] 能解释上下文窗口为什么不是永久记忆。
- [ ] 能说清 `system`、`user`、`assistant` 的职责。
- [ ] 能解释低 Temperature 为什么适合结构化和合规任务。
- [ ] 能说明当前公司模型接口对 Temperature 的支持仍需验证。

---

## 现有滑动窗口代码详解

### 1. 滑动窗口解决什么问题

模型本身不会永久记住上一次独立 API 请求。为了让模型理解连续对话，程序需要在新请求中重新发送相关历史消息。

如果把所有历史对话都发送给模型，会出现三个问题：

- 历史消息不断占用 Token，最终可能超过上下文窗口。
- 调用成本和处理时间会增加。
- 太多无关旧信息可能干扰当前回答。

滑动窗口的做法是：只保留最近若干轮完整问答，新问答加入后，最早的一轮自动离开窗口。

```text
旧轮次 ← [最近第 2 轮] [最近第 1 轮] ← 新轮次
              窗口只保留固定数量
```

### 2. `deque` 是什么

```python
from collections import deque
```

- `deque` 全称是 **double-ended queue**，中文叫**双端队列**。
- 普通队列通常从一端加入、另一端取出。
- 双端队列可以高效地从左端或右端添加、删除元素。
- 当前代码利用它的 `maxlen` 功能自动淘汰最旧数据。

### 3. 初始化窗口

```python
class ConversationContext:
    def __init__(self, max_rounds: int = 3) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds 必须大于等于 1")

        self.max_rounds = max_rounds
        self._rounds: deque[tuple[str, str]] = deque(
            maxlen=max_rounds
        )
```

逐项解释：

- `ConversationContext` 表示一次会话的上下文管理器。
- `max_rounds: int = 3` 表示默认保留最近 3 轮已经完成的对话。
- 一轮对话是一个 `(用户消息, 模型回答)` 元组，而不是一条单独消息。
- `max_rounds < 1` 时立即报错，因为保留 0 轮或负数轮没有正常业务含义。
- `_rounds` 前面的下划线表示它是类的内部数据，外部代码不应随意修改。
- `deque[tuple[str, str]]` 是类型标注：队列中的每个元素都是包含两个字符串的元组。
- `deque(maxlen=max_rounds)` 设置固定容量。容量已满时再次 `append()`，最左边也就是最旧的一轮会被自动删除。

例如：

```python
context = ConversationContext(max_rounds=2)
```

此时最多保存两个这样的元素：

```python
deque([
    ("问题2", "回答2"),
    ("问题3", "回答3"),
], maxlen=2)
```

### 4. 保存完整问答

```python
def add_round(
    self,
    user_message: str,
    assistant_message: str,
) -> None:
```

这个方法接收一次已经完成的用户问题和模型回答。

```python
if not user_message.strip():
    raise ValueError("用户消息不能为空")

if not assistant_message.strip():
    raise ValueError("模型回复不能为空")
```

`strip()` 会临时去掉字符串两端的空白。如果消息是 `"   "`，去掉空白后变成空字符串，因此会报错。这里的 `strip()` 只用于判断，原消息仍按原样保存。

```python
self._rounds.append(
    (user_message, assistant_message)
)
```

用户消息和模型回答被作为一个元组一起加入队列。这样可以确保淘汰时删掉的是一整轮，而不是只删问题或只删回答。

### 5. 为什么必须保存完整轮次

只保留用户消息时，模型不知道自己以前回答过什么；只保留模型回答时，模型不知道回答对应什么问题。

```text
正确：user 问题1 → assistant 回答1
错误：              assistant 回答1   # 缺少问题
错误：user 问题1                    # 缺少回答
```

完整轮次能够让模型理解对话的因果和指代关系。

### 6. 组装下一次 API 输入

```python
def build_input(
    self,
    current_user_message: str,
) -> list[dict[str, str]]:
```

返回类型是字典列表，每个字典包含 `role` 和 `content`，符合当前 Responses API 的消息输入形式。

首先检查当前问题：

```python
if not current_user_message.strip():
    raise ValueError("当前用户消息不能为空")
```

然后创建一个新的空列表：

```python
messages: list[dict[str, str]] = []
```

遍历窗口中的历史轮次：

```python
for user_message, assistant_message in self._rounds:
    messages.append({
        "role": "user",
        "content": user_message,
    })
    messages.append({
        "role": "assistant",
        "content": assistant_message,
    })
```

每个元组被恢复为两条有角色的消息，并按照原始时间顺序加入列表。

最后加入当前问题：

```python
messages.append({
    "role": "user",
    "content": current_user_message,
})
```

当前问题只有 `user` 消息，因为模型还没有回答。等 API 成功返回答案后，它们才会一起成为一轮完整历史。

### 7. `__len__` 的作用

```python
def __len__(self) -> int:
    return len(self._rounds)
```

定义这个特殊方法后，可以直接写：

```python
len(context)
```

它返回的是已保存的**问答轮数**，不是消息条数，也不是 Token 数。例如窗口中有两轮问答时，实际有四条历史消息，但 `len(context)` 返回 2。

### 8. 四轮对话运行轨迹

假设：

```python
context = ConversationContext(max_rounds=2)
```

#### 第 1 次调用

窗口最初为空，发送：

```python
[
    {"role": "user", "content": "问题1"},
]
```

模型返回“回答1”后，保存：

```text
[(问题1, 回答1)]
```

#### 第 2 次调用

发送一轮历史和当前问题：

```python
[
    {"role": "user", "content": "问题1"},
    {"role": "assistant", "content": "回答1"},
    {"role": "user", "content": "问题2"},
]
```

模型返回“回答2”后，保存：

```text
[(问题1, 回答1), (问题2, 回答2)]
```

#### 第 3 次调用

此时窗口已经有两轮。发送：

```python
[
    {"role": "user", "content": "问题1"},
    {"role": "assistant", "content": "回答1"},
    {"role": "user", "content": "问题2"},
    {"role": "assistant", "content": "回答2"},
    {"role": "user", "content": "问题3"},
]
```

模型返回“回答3”后，执行 `append((问题3, 回答3))`。因为容量只有 2，最旧的第 1 轮自动被删除：

```text
[(问题2, 回答2), (问题3, 回答3)]
```

#### 第 4 次调用

发送：

```python
[
    {"role": "user", "content": "问题2"},
    {"role": "assistant", "content": "回答2"},
    {"role": "user", "content": "问题3"},
    {"role": "assistant", "content": "回答3"},
    {"role": "user", "content": "问题4"},
]
```

这就是此前测试得到问题2、回答2、问题3、回答3、问题4的原因。

### 9. 滑动窗口如何接入 `chat()`

```python
if context is None:
    model_input = user_message
else:
    model_input = context.build_input(user_message)
```

- 没有传入 `context`：这是单轮聊天，只把当前字符串发给模型。
- 传入 `context`：这是多轮聊天，把历史消息和当前问题一起发给模型。

请求部分：

```python
response = client.responses.create(
    model=get_required_env("LLM_MODEL"),
    instructions=system_message,
    input=model_input,
)
```

- `model`：指定模型名称。
- `instructions`：每次请求都单独发送系统消息。
- `input`：当前问题，或者“历史问答 + 当前问题”的消息列表。

系统消息没有存入 `_rounds`，所以不会被 `deque` 淘汰。只要每次调用 `chat()` 时继续传递同一条 `system_message`，模型就始终能看到行为规则。

### 10. 为什么先检查回答，再保存历史

```python
content = response.output_text.strip()

if not content:
    raise RuntimeError("模型返回了空内容")

if context is not None:
    context.add_round(user_message, content)
```

执行顺序很重要：

1. 调用 API。
2. 读取回答。
3. 检查回答不是空内容。
4. 最后才将问题和回答加入历史。

如果 API 请求失败或模型返回空内容，这一轮不会写入上下文。这样不会留下“有用户问题但没有模型回答”的残缺历史。

### 11. 当前实现的优点

- 以完整问答为单位保存和淘汰。
- 使用 `deque(maxlen=...)` 自动删除最旧轮次，逻辑简单。
- 空问题和空回答都有校验。
- 每次重新构造消息列表，不直接暴露内部队列。
- API 成功且回答非空后才保存该轮。
- 系统指令每次单独发送，不受滑动窗口影响。

### 12. 当前实现的边界

#### 不是按真实 Token 数控制

`max_rounds=2` 只代表最多保留两轮。某一轮如果包含很长的政策文档，即使只有一轮，也可能消耗大量 Token 或超过模型限制。

后续更可靠的方案是估算 Token，并同时限制轮数和 Token 总量。

#### 删除后不会自动总结

最旧轮次被删除后，其中的信息彻底丢失。当前实现没有把旧消息压缩成摘要。候选地块编号等重要事实如果只在很早的对话里出现，后续可能无法继续记住。

#### 只存在于当前 Python 进程

上下文保存在内存中。程序重启后，`deque` 消失，不属于长期记忆。若需要跨进程保存，需要数据库、Redis 或文件存储。

#### 每个用户必须拥有独立实例

如果 Web 服务把同一个 `ConversationContext` 实例共享给所有用户，甲用户的对话可能进入乙用户的上下文，造成数据混淆和隐私问题。未来接入 FastAPI 时，应按会话或用户隔离上下文。

#### 系统消息一致性由调用者负责

系统消息不在 `ConversationContext` 中。如果不同调用给同一个上下文传入不同的 `system_message`，模型行为规则也会变化。后续可以把固定系统规则集中配置，避免误传。

### 13. 三个最低验收问题

**为什么使用 `deque(maxlen=max_rounds)`？**

因为它可以只保存固定数量的最近问答。容量满后加入新轮次时，最旧轮次会自动删除，不需要手动判断和切片。

**为什么一轮对话必须同时保留 `user` 和 `assistant`？**

因为问题和回答共同组成完整语义。缺少任意一方，模型都难以理解之前发生了什么。

**为什么系统消息不放进会淘汰的窗口？**

因为系统消息规定模型身份和长期行为边界。当前代码通过每次请求的 `instructions` 单独发送，使它始终存在，不会随旧对话被删除。

### 14. 一句话闭卷复述

> 当前滑动窗口使用固定长度的双端队列保存最近若干轮完整问答；每次请求把历史 `user/assistant` 消息与当前问题组装为 `input`，系统规则则通过 `instructions` 单独发送；API 成功返回后才保存新一轮，但它目前按轮数而非 Token 数控制，也没有摘要、持久化和多用户会话隔离。
