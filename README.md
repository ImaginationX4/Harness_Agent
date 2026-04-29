## Harness Agent 的最小形式化

我把 Anthropic 那几篇博客压成一个定义:

设:

- $\Sigma$ = 会话状态(append-only 事件流)
- $\mathcal{T} = {t_i : \text{Args}_i \to \text{Result}_i}$ = 工具集
- $M : \text{Context} \to \text{Response}$ = 模型调用
- $\pi : \text{Response} \to (\text{ToolCall}^* \cup \text{Halt})$ = 响应解析
- $\rho : \Sigma \to \text{Context}$ = 上下文渲染(含压缩/重置)
- $\varepsilon : \Sigma \to {\text{continue}, \text{done}}$ = 终止判定

那么 harness 就是这一个不动点循环:

$$H(\sigma) = \begin{cases} \sigma & \text{if } \varepsilon(\sigma) = \text{done} \ H(\sigma \oplus {M(\rho(\sigma))} \oplus \text{exec}(\pi(M(\rho(\sigma))))) & \text{otherwise} \end{cases}$$
这里的 $\oplus$ **不是异或（XOR）**，是**事件流追加（append）**。
**这个式子就是全部**。所有博客里讲的初始化 agent、context reset、generator/evaluator、并行 git 协作,全部是对 $\langle \mathcal{T}, \rho, \pi, \varepsilon \rangle$ 四元组的特化。


---

## 式子语义还原

$\Sigma$ 被定义为 append-only 事件流，类比一个只能往后写的日志数组：

```
σ = [event_0, event_1, event_2, ...]
```

所以 $\sigma \oplus x$ 的意思是：**把 x 追加到这个流的末尾，得到新的流**。

$$\sigma \oplus {e} = [event_0, ..., event_n, e]$$

---

## 拆解整个式子

$$H(\sigma \oplus {M(\rho(\sigma))} \oplus \text{exec}(\pi(M(\rho(\sigma)))))$$

从内到外读：

|表达式|含义|
|---|---|
|$\rho(\sigma)$|把当前事件流渲染成模型的 context（即拼 prompt）|
|$M(\rho(\sigma))$|调用模型，得到 response|
|$\sigma \oplus {M(\cdot)}$|把这条 response 追加进流|
|$\pi(M(\cdot))$|解析 response，得到要执行的 tool_call 列表（或 Halt）|
|$\text{exec}(\pi(\cdot))$|执行这些工具，得到结果事件|
|$\sigma \oplus {\cdot} \oplus \text{exec}(\cdot)$|把 response + 工具结果都追加进流|
|$H(\sigma')$|用新流递归继续|



# H1 - 第一阶段极简AI Agent原型

这是我的第一阶段AI Agent探索成果，一个能让大模型自主调用Shell命令完成任务的极简原型实现。


## 📖 项目介绍

H1是我从零开始构建的第一个AI Agent，核心验证了「大模型+工具调用」的基础能力：让大模型自主分析用户需求，分步调用Shell工具完成任务，直到得到最终结果。

本项目作为第一阶段探索，核心是最小可行性验证，代码简洁，逻辑清晰，方便后续迭代升级。

## ✨ 核心功能
- 🛠️ 支持大模型原生工具调用能力
- 🖥️ 内置Shell命令执行工具，允许大模型自主运行系统命令完成任务
- 🔌 兼容OpenAI格式API，可轻松对接火山方舟/OpenAI等各类大模型服务
- 🔄 支持多轮迭代自动执行，直到任务完成
- 📝 完整的执行日志输出，方便调试追踪

## 🛠️ 技术栈
- Python 3.8+
- OpenAI Python SDK（兼容格式）
- 字节跳动火山方舟豆包API
- python-dotenv（环境变量管理）

## 🚀 快速开始

### 1. 克隆项目
```bash
git clone https://github.com/[你的用户名]/H1.git
cd H1
```

### 2. 安装依赖
```bash
pip install openai python-dotenv
```

### 3. 配置API
你可以通过两种方式配置大模型API：
1. 环境变量方式（推荐）：创建`.env`文件填入你的API信息
```env
API_KEY=你的API密钥
MODEL_ID=你的模型endpoint ID
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```
2. 直接修改`H1.py`中的配置项（开发测试用）

### 4. 运行Agent
修改`H1.py`底部的任务描述，然后运行：
```bash
python H1.py
```

## 💡 使用示例
你可以让H1帮你完成各种需要和本地文件/系统交互的任务，比如：
```python
# 总结当前代码仓库架构
run_agent("阅读当前目录下的Harness_Engineering代码仓库，总结它的架构设计，分析核心选择的代数结构，生成README文件")

# 清理项目临时文件
run_agent("找出当前目录下所有大于100MB的日志文件，删除它们")
```

## ⚠️ 注意事项
1. **安全提示**：本Agent允许大模型执行任意Shell命令，请仅在开发环境/隔离容器中运行，不要在生产环境或带敏感数据的环境中使用
2. API密钥：不要将你的API密钥提交到公开仓库，示例代码中的密钥请替换为你自己的
3. 迭代次数：默认最大50次迭代，可以根据任务复杂度修改`max_iterations`参数

## 🎯 阶段说明
- `H1` = 第一阶段（Phase 1）：核心验证大模型工具调用+自主执行的基础能力，完成最小原型验证
- 后续会基于H1的经验迭代更复杂的Agent架构，增加更多工具、更复杂的规划能力等

## 📄 许可证
MIT License
