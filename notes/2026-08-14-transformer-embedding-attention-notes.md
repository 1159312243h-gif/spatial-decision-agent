# 2026-08-14 Transformer、Embedding 与 Attention 学习笔记

## 1. 今日学习目标

完成本文学习后，应当能够：

1. 解释文本如何从字符串变成模型可以计算的向量。
2. 区分 Token、Token ID、Token Embedding 和句向量 Embedding。
3. 解释 Transformer 为什么需要位置信息。
4. 复述 Self-Attention 的 `QK^T -> 缩放 -> Mask -> Softmax -> 乘 V` 流程。
5. 说明 Multi-Head Attention、FFN、残差连接和归一化的职责。
6. 画出 Decoder-only Transformer 的最小数据流。
7. 用约 5 分钟完整讲清这些组件，而不是只背术语。

---

## 2. 核心术语与全称

| 缩写或术语 | 英文全称 | 中文含义 | 核心作用 |
|---|---|---|---|
| Token | Token | 词元、标记 | 模型处理文本的基本离散单位 |
| Tokenizer | Tokenizer | 分词器、标记器 | 文本与 Token ID 之间的编码、解码 |
| Token ID | Token Identifier | Token 编号 | Token 在词表中的整数索引 |
| Embedding | Embedding | 嵌入、向量表示 | 把离散编号转换为连续向量 |
| PE | Positional Encoding | 位置编码 | 向模型提供顺序和相对位置信息 |
| Q | Query | 查询向量 | 当前 Token 想寻找什么信息 |
| K | Key | 键向量 | 每个 Token 用什么特征接受匹配 |
| V | Value | 值向量 | 匹配后实际提供什么内容 |
| Attention | Attention | 注意力机制 | 根据相关度汇总其他 Token 的信息 |
| MHA | Multi-Head Attention | 多头注意力 | 同时学习多种关系和表示子空间 |
| FFN | Feed-Forward Network | 前馈神经网络 | 对每个位置的特征进行非线性变换 |
| MLP | Multi-Layer Perceptron | 多层感知机 | Transformer 中常作为 FFN 的实现 |
| LayerNorm | Layer Normalization | 层归一化 | 稳定每个 Token 表示的数值尺度 |
| RMSNorm | Root Mean Square Normalization | 均方根归一化 | 现代大模型常用的简化归一化方式 |
| LM Head | Language Model Head | 语言模型输出头 | 将隐藏向量映射到词表分数 |
| Logits | Logits | 未归一化分数 | Softmax 前每个候选 Token 的分数 |
| KV Cache | Key-Value Cache | 键值缓存 | 生成时复用历史 Token 的 K、V |

---

## 3. 一条完整的数据流

```text
原始文本
  -> Tokenizer
Token 序列
  -> 查词表
Token ID 序列
  -> Token Embedding
连续向量序列
  -> 加入或注入位置信息
带顺序信息的向量序列
  -> 多层 Transformer Block
上下文化隐藏向量
  -> LM Head
词表 Logits
  -> Softmax / 解码策略
下一个 Token
```

以文本“物流园靠近高速”为例，概念上可能经历：

```text
"物流园靠近高速"
-> ["物流", "园", "靠近", "高速"]
-> [15237, 861, 4920, 7362]
-> 四个 d_model 维向量
-> 融合位置和上下文
-> 预测下一个 Token
```

实际 Token 如何切分由具体模型的 Tokenizer 决定，不能认为一个汉字或一个单词必然等于一个 Token。

---

## 4. Token ID 与 Token Embedding

### 4.1 Token ID 只是索引

假设词表中存在：

```text
"物流" -> 15237
"园"   -> 861
```

`15237` 只是词表中的位置，不表示“物流”比编号为 861 的“园”更大、更重要或更相似。

Token ID 不能直接用距离表达语义：

```text
abs(15237 - 861)
```

这个差值没有语言学意义。

### 4.2 Embedding 是可计算的连续向量

模型维护一个可训练的 Embedding 矩阵：

```text
E 的形状 = [词表大小 V, 隐藏维度 d_model]
```

Token ID 相当于查表行号：

```text
x_i = E[token_id_i]
```

得到的 `x_i` 是一个浮点向量：

```text
[0.12, -0.35, 0.81, ...]
```

训练过程中，Embedding 矩阵与模型其他参数一起更新，使向量逐渐适合预测任务。

### 4.3 Token Embedding 不是完整上下文语义

刚查表得到的 Token Embedding 主要由 Token 身份决定，还没有充分结合当前句子。

例如“苹果”可能表示水果，也可能表示公司。初始 Token Embedding 相同，但经过多层 Self-Attention 后，它的隐藏向量会根据上下文发生变化：

```text
我吃了一个苹果。       -> 更接近水果语义
苹果发布了新款电脑。   -> 更接近公司语义
```

因此需要区分：

```text
初始 Token Embedding：查表得到的基础表示
上下文化隐藏向量：经过 Transformer 后结合当前上下文的表示
```

### 4.4 与 RAG 中 Embedding 的区别

RAG 常说的 Embedding 通常是句子、段落或文档向量，用于相似度检索；Token Embedding 是模型内部每个 Token 的初始向量。

| 对象 | 常见用途 |
|---|---|
| Token Embedding | Transformer 内部计算 |
| 句子/文档 Embedding | 向量数据库检索、聚类、相似度 |

二者都使用连续向量，但粒度和任务不同。

---

## 5. 为什么需要位置信息

### 5.1 Attention 不天然理解顺序

仅看 Token 集合：

```text
狗 咬 人
人 咬 狗
```

它们包含相同 Token，但语义不同。模型必须知道谁在前、谁在后以及相隔多远。

### 5.2 常见位置方案

1. **正弦/余弦位置编码**：使用固定数学函数产生位置向量。
2. **可学习绝对位置向量**：为每个位置训练一个向量。
3. **RoPE**：Rotary Position Embedding，旋转位置嵌入；将位置信息作用到 Q、K，使注意力分数能够表达相对位置。

“加入位置信息”是概念性说法。传统方法可能把位置向量加到 Token Embedding 上，而 RoPE 通常不是简单相加，而是对 Q、K 做与位置相关的旋转变换。

---

## 6. Self-Attention 详细流程

### 6.1 输入张量

设序列长度为 `n`，隐藏维度为 `d_model`：

```text
X 的形状 = [n, d_model]
```

`X` 中每一行对应一个 Token 的当前表示。

### 6.2 生成 Q、K、V

模型通过三个可学习矩阵进行线性投影：

```text
Q = X W_Q
K = X W_K
V = X W_V
```

直观理解：

- Q：当前 Token 为完成任务正在查询什么。
- K：每个 Token 对外展示哪些可匹配特征。
- V：如果该 Token 被关注，实际贡献什么信息。

Q、K、V 不是三个原始单词，而是同一批 Token 表示经过不同参数投影后得到的三组向量。

### 6.3 计算匹配分数

```text
Scores = Q K^T
```

其中第 `i` 行第 `j` 列表示第 `i` 个 Token 的 Q 与第 `j` 个 Token 的 K 的点积。

点积越大，一般表示当前 Query 与该 Key 越匹配。

### 6.4 为什么除以 sqrt(d_k)

缩放点积注意力使用：

```text
ScaledScores = Q K^T / sqrt(d_k)
```

当向量维度 `d_k` 较大时，点积的数值幅度通常也会变大。过大的分数进入 Softmax 后，概率可能过度集中在少数位置，使梯度变小、训练不稳定。

除以 `sqrt(d_k)` 可以控制分数尺度，让 Softmax 保持在更适合学习的数值范围。

### 6.5 Mask

Decoder-only 模型进行生成时使用 Causal Mask，也叫因果遮罩。

位置 `i` 只能查看：

```text
位置 0 到位置 i
```

不能查看未来位置，否则训练时会偷看到答案。

概念示例：

```text
Token 1: 可看 1
Token 2: 可看 1, 2
Token 3: 可看 1, 2, 3
```

Padding Mask 则用于忽略批处理中补齐长度的无效位置。两者目的不同。

### 6.6 Softmax 转成权重

```text
A = Softmax(ScaledScores + Mask)
```

Softmax 按行把分数转换成非负权重，每一行的权重之和为 1。

这一步回答：

```text
当前 Token 应该从每个可见 Token 获取多少信息？
```

### 6.7 加权汇总 V

```text
O = A V
```

每个 Token 使用注意力权重，对所有可见 Token 的 V 做加权求和，得到结合上下文的新表示。

完整公式：

```text
Attention(Q, K, V)
= Softmax((Q K^T / sqrt(d_k)) + Mask) V
```

---

## 7. Self-Attention 为什么能融合上下文

考虑句子：

```text
苹果发布了新款电脑。
```

处理“苹果”时，模型可能对“发布”“电脑”等 Token 分配更高权重。加权汇总它们的 V 后，“苹果”的新表示便包含公司和产品发布语境。

核心不是“某个词自己变聪明”，而是：

```text
每个 Token 都根据自己的 Q
与所有可见 Token 的 K 比较
再按权重汇总这些 Token 的 V
```

多层堆叠后，信息可以逐层传播，形成更加复杂的上下文表示。

---

## 8. Multi-Head Attention

### 8.1 为什么需要多个头

一个注意力头只产生一套匹配和汇总方式。不同关系可能需要不同表示子空间：

- 语法关系。
- 实体与属性。
- 指代关系。
- 时间和空间关系。
- 局部搭配与长距离依赖。

多个头可以同时学习不同模式，但不能把某个头永久解释成固定的人类概念。模型并没有保证“第 3 个头一定负责地点”。

### 8.2 计算形式

每个头独立投影并计算：

```text
head_i = Attention(X W_Q_i, X W_K_i, X W_V_i)
```

然后拼接并输出投影：

```text
MHA(X) = Concat(head_1, ..., head_h) W_O
```

多头的作用重点是扩展模型表达不同关系的能力，不只是重复计算相同结果。

---

## 9. FFN 做什么

### 9.1 Attention 与 FFN 的分工

```text
Attention：不同 Token 之间交换和汇总信息
FFN：每个 Token 独立加工已经汇总的特征
```

Attention 会沿序列维度混合信息；FFN 通常对每个位置使用同一套参数，不直接让不同位置互相通信。

### 9.2 简化公式

经典 FFN：

```text
FFN(x) = W_2 activation(W_1 x + b_1) + b_2
```

通常先把维度扩大，再通过激活函数加入非线性，最后投影回 `d_model`。

现代模型也可能使用 GELU、SwiGLU 等激活或门控结构，但核心职责仍是进行逐位置的非线性特征变换。

---

## 10. 残差连接与归一化

### 10.1 残差连接

```text
y = x + SubLayer(x)
```

主要作用：

1. 保留原始信息通道。
2. 让子层重点学习对输入的增量修改。
3. 改善深层网络的梯度传播。
4. 降低深层堆叠的训练难度。

残差连接不是简单“防止忘记”，更准确地说，它提供了直接的信息和梯度路径。

### 10.2 LayerNorm 与 RMSNorm

归一化用于控制表示的数值尺度，使训练更加稳定。

常见布局：

- Post-Norm：先子层和残差，再归一化。
- Pre-Norm：先归一化，再进入子层并做残差。

现代大模型常采用 Pre-Norm 或 RMSNorm，但不同模型实现可能不同，不能假设所有 Transformer 完全一致。

---

## 11. Decoder-only Transformer Block

GPT、Qwen 等生成式大模型通常使用 Decoder-only 架构。一个简化的 Pre-Norm Block：

```text
x
|-> Norm -> Causal Multi-Head Self-Attention -> + x
|-> Norm -> FFN / MLP                         -> + residual
`-> 下一层
```

展开为：

```text
h_1 = x + Attention(Norm(x))
h_2 = h_1 + FFN(Norm(h_1))
```

多个 Block 重复堆叠后，最后经过归一化与 LM Head 得到词表 Logits。

---

## 12. Encoder、Encoder-Decoder 与 Decoder-only

### Encoder-only

典型任务：文本理解、分类、序列标注。

通常使用双向 Self-Attention，一个 Token 可以观察左右两侧上下文。

### Encoder-Decoder

典型任务：翻译、输入到输出的序列转换。

- Encoder 编码输入。
- Decoder 使用因果 Self-Attention 处理已生成内容。
- Decoder 通过 Cross-Attention 读取 Encoder 表示。

### Decoder-only

典型任务：自回归文本生成。

使用因果 Self-Attention，根据已有 Token 逐步预测下一个 Token。当前项目调用的生成式模型应从这个直观框架理解，但具体公司模型内部实现仍应以其真实技术说明为准。

---

## 13. 模型如何生成下一个 Token

最后一层产生隐藏向量后，LM Head 将其映射到词表大小：

```text
hidden_state -> logits[V]
```

每个 Logit 对应一个候选 Token。模型再根据解码策略选择下一个 Token：

- Greedy：选概率最高者。
- Temperature：调整分布尖锐程度。
- Top-k：只在概率最高的 k 个候选中采样。
- Top-p：在累计概率达到 p 的候选集合中采样。

选出一个 Token 后，将其追加到序列，再进行下一步预测，直到结束条件满足。

### KV Cache

生成第 `t` 个 Token 时，前面 Token 的 K、V 已经计算过。KV Cache 保存这些历史结果，避免每一步重复计算全部历史 K、V。

它主要降低自回归生成的重复计算和延迟，但会占用显存。

---

## 14. 最常见的概念混淆

### 混淆 1：Token ID 是语义大小

错误。Token ID 只是词表索引。

### 混淆 2：Embedding 已经包含完整上下文

不准确。初始 Token Embedding 是基础表示；经过 Transformer 后的隐藏向量才结合当前上下文。

### 混淆 3：位置编码只有一种

错误。可以使用固定、可学习、RoPE 等不同方案。

### 混淆 4：Q、K、V 是三个不同单词

错误。它们通常来自同一输入表示经过三个不同线性投影。

### 混淆 5：Attention 权重等于严格的人类解释

不应这样断言。权重说明模型内部的信息聚合比例，但不能自动等同于完整因果解释。

### 混淆 6：Attention 完成所有计算

错误。FFN、残差、归一化、位置机制、输出层同样重要。

### 混淆 7：多头就是每个头固定负责一种语法功能

没有这种保证。不同头可能学习不同模式，但解释通常不是永久固定的。

### 混淆 8：Temperature 属于 Transformer Block

通常不是。Temperature 一般作用在输出 Logits 或概率分布的解码阶段。

---

## 15. 与选址 Agent 项目的关系

Transformer 和 Attention 负责模型内部的语言理解与生成，但不能替代确定性业务组件：

| 任务 | 合适组件 |
|---|---|
| 理解用户选址需求 | LLM |
| 抽取结构化字段 | LLM + Pydantic 校验 |
| 选择已注册工具 | Function Calling + 应用程序控制 |
| 计算空间相交、距离、面积 | GeoPandas/PostGIS 等 GIS 工具 |
| 执行硬性合规规则 | RuleEngine |
| 组织解释和报告 | LLM，但必须引用真实工具结果 |

即使大模型内部使用强大的 Transformer，也不应该让它凭语言直觉计算真实空间面积或发布最终法定合规结论。

---

## 16. 十张知识卡

### 卡片 1：Token ID 与 Embedding

Token ID 是离散词表索引；Embedding 是通过查表得到的连续向量，用于神经网络计算。

### 卡片 2：位置编码

Attention 不天然表达顺序，因此需要绝对或相对位置信息；RoPE 常通过旋转 Q、K 表达位置关系。

### 卡片 3：Q、K、V

Q 表示查询需求，K 表示匹配特征，V 表示匹配后提供的内容。

### 卡片 4：缩放点积注意力

`Softmax(QK^T / sqrt(d_k) + Mask)V`；缩放用于控制点积分数幅度，避免 Softmax 过度饱和。

### 卡片 5：因果遮罩

生成模型中当前位置只能观察自己和之前的 Token，不能观察未来 Token。

### 卡片 6：多头注意力

多个头在不同投影子空间中同时学习关系，结果拼接后再投影。

### 卡片 7：Attention 与 FFN

Attention 负责 Token 间信息交互；FFN 负责对每个 Token 的特征进行非线性加工。

### 卡片 8：残差连接

将输入直接加回子层输出，为信息和梯度提供直接路径，使深层网络更容易训练。

### 卡片 9：归一化

LayerNorm/RMSNorm 控制表示尺度并提升训练稳定性；具体模型可能采用不同布局。

### 卡片 10：Decoder-only 生成

使用因果 Self-Attention，根据已有 Token 产生 Logits，再通过解码策略逐 Token 生成。

---

## 17. 五条闭卷评测样例

先只看问题并口头回答，再查看第 18 节参考答案。

### 题目 1

Token ID 与 Token Embedding 有什么区别？为什么不能直接把 Token ID 当作语义数值？

### 题目 2

为什么 Transformer 需要位置信息？RoPE 与简单相加位置向量有什么区别？

### 题目 3

不看公式，先用自然语言解释 Q、K、V；然后写出 Scaled Dot-Product Attention 的完整流程。

### 题目 4

Attention 和 FFN 的职责有什么不同？如果只有 Attention 而没有 FFN，会缺少什么能力？

### 题目 5

残差连接和归一化各自解决什么问题？为什么二者不能当作同一个概念？

### 建议评分

每题 0-2 分，共 10 分：

- 0 分：无法解释或核心方向错误。
- 1 分：方向正确，但遗漏关键机制。
- 2 分：概念、流程和边界均解释清楚。

达到 8 分可视为今日基本验收通过；不足 8 分时，只复习答错部分。

---

## 18. 五条评测参考答案与得分点

建议先独立完成第 17 节，再阅读本节。每题满分 2 分：两个核心得分点各 1 分。

### 答案 1

Token ID 是 Token 在词表中的整数索引，编号差值没有语义距离意义。Token Embedding 是从可训练矩阵中查出的连续向量，模型可以对它进行线性变换、点积等计算。初始 Token Embedding 也不等于完整上下文语义，后者需要 Transformer 层进一步形成。

得分点：

1. 说清 Token ID 只是离散索引，编号大小和差值没有语义意义。
2. 说清 Embedding 是可训练的连续向量，并区分初始 Embedding 与上下文化隐藏向量。

### 答案 2

Attention 本身主要根据内容匹配，若没有位置信息，难以区分相同 Token 的不同排列。传统位置方案可能把位置向量加到输入表示中；RoPE 通常对 Q、K 进行位置相关旋转，使注意力分数包含相对位置信息。

得分点：

1. 说明没有位置信息时，模型难以区分相同 Token 的不同排列。
2. 说明 RoPE 主要对 Q、K 做位置相关旋转，而不只是把位置向量简单加到输入上。

### 答案 3

Q 是当前 Token 的查询需求，K 是各 Token 对外提供的匹配特征，V 是被关注后实际提供的信息。先用 Q 与所有 K 点积，除以 `sqrt(d_k)` 控制尺度，再加入 Mask，经过 Softmax 得到权重，最后使用权重对 V 加权求和。

得分点：

1. 正确解释 Q、K、V 的三个不同职责。
2. 完整写出 `QK^T -> 缩放 -> Mask -> Softmax -> 乘 V`，并知道输出是上下文加权表示。

### 答案 4

Attention 让不同 Token 交换和聚合信息；FFN 对每个 Token 当前表示进行非线性特征变换。只有 Attention 会缺少逐位置的强非线性特征加工能力，Transformer Block 的表达能力会受到限制。

得分点：

1. 说明 Attention 沿序列维度完成 Token 之间的信息交互。
2. 说明 FFN 对每个位置独立进行非线性特征加工，二者不能互相替代。

### 答案 5

残差连接通过 `x + SubLayer(x)` 保留直接的信息与梯度路径，使深层网络更容易优化；归一化控制表示的数值尺度，使训练更稳定。一个负责建立跳跃路径，一个负责稳定数值分布，不能混为同一机制。

得分点：

1. 说明残差连接为信息和梯度提供直接路径，帮助训练深层网络。
2. 说明归一化用于控制数值尺度、稳定训练，并明确它与残差连接职责不同。

### 五题一页速答

1. **Token ID 与 Embedding**：前者是无语义大小关系的词表索引，后者是可训练、可计算的连续向量。
2. **位置信息**：用于区分 Token 顺序；RoPE 通过旋转 Q、K 将相对位置影响注入注意力分数。
3. **Self-Attention**：Q 提问、K 接受匹配、V 提供内容；经过点积、缩放、遮罩、Softmax 后加权汇总 V。
4. **Attention 与 FFN**：Attention 负责 Token 间交流，FFN 负责逐 Token 的非线性特征加工。
5. **残差与归一化**：残差建立信息和梯度直通路径，归一化稳定数值尺度。

---

## 19. 五分钟闭卷讲解提纲

### 0:00-0:40：输入如何进入模型

说明文本先经过 Tokenizer 得到 Token ID，再通过 Embedding 矩阵变成连续向量；Token ID 只是索引，Embedding 才能参与模型计算。

### 0:40-1:15：为什么需要位置

举“狗咬人”和“人咬狗”的例子，说明 Attention 不天然知道顺序，因此需要位置编码或 RoPE。

### 1:15-2:30：Self-Attention

解释 Q、K、V，并复述：

```text
QK^T -> 除以 sqrt(d_k) -> 加 Mask -> Softmax -> 乘 V
```

说明加权汇总 V 后，每个 Token 能结合可见上下文。

### 2:30-3:10：多头注意力

说明多个头通过不同投影同时学习多种关系，但不能武断地给每个头固定人类含义。

### 3:10-3:50：FFN、残差和归一化

说明 Attention 负责 Token 交流，FFN 负责逐 Token 加工；残差提供信息和梯度通道，归一化稳定数值尺度。

### 3:50-4:30：Transformer Block 与生成

说明多个 Block 堆叠，最终隐藏向量经过 LM Head 得到词表 Logits，再用解码策略选择下一个 Token。

### 4:30-5:00：项目边界

说明 Transformer 帮助 LLM 理解和生成语言，但 GIS 空间计算必须交给 GeoPandas/PostGIS，硬规则交给 RuleEngine，LLM 不能凭语言直觉发布最终合规结论。

---

## 20. 今日验收清单

- [ ] 能区分 Token ID、Token Embedding 和上下文化隐藏向量。
- [ ] 能解释位置编码存在的原因。
- [ ] 能闭卷写出 Attention 完整流程。
- [ ] 能解释除以 `sqrt(d_k)` 的原因。
- [ ] 能区分 Attention 与 FFN。
- [ ] 能解释残差连接与归一化的不同职责。
- [ ] 完成五条闭卷评测并达到 8 分。
- [ ] 完成一次约 5 分钟的讲解录音。
- [ ] 把答错部分写入当天学习记录。

一句话总结：

> Tokenizer 将文本变成 Token ID，Embedding 将离散编号变成连续向量，位置机制补充顺序，Self-Attention 负责上下文信息交互，FFN 负责逐 Token 非线性加工，残差与归一化保证深层网络能够稳定训练，最终 LM Head 和解码策略完成逐 Token 生成。
