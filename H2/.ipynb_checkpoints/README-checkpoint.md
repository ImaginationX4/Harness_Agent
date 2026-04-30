# H1 Harness — V2
> 给 Anthropic harness 系列博客一个**有形式规约**的可执行版。
> 每一版的 commit 都对应一个形式化命题，每一个工具都有可证伪的契约。

## V2 改动：从 L1 跨入 L2/L3
V1 的 harness 只能跑短命令(L1)。真实任务一旦涉及「启动服务器→访问网页→验证用户能用」，就跨进了 **L2（资源生命周期）** 和 **L3（端到端语义）**。V2 补齐对应能力。

### 新增工具
| 工具 | 层级 | 作用 |
|---|---|---|
| `start_service` / `stop_service` / `check_service` | L2 | 后台进程生命周期 + 服务注册表不变式维护 |
| `http_check` | L1/L2 | HTTP 状态码 + 页面关键字断言校验 |
| `browser_check` | L3 | Playwright 端到端：填表→点击→结果校验 |

### 形式化契约
每个工具不只返回执行结果，强制要求 LLM 给出**可证伪预测**：
- `expect_contains: ["收益率", "胜率"]`：LLM 必须提前声明期待看到的关键内容
- 工具返回 `hits: {关键字: 是否命中}`：逐项明确命中/未命中
- 统一 `[ok] / [fail]` 状态标识：仅当实际结果与 LLM 预测完全对齐，才算校验通过


## Service FSM（L2 状态机）
```
ServiceState = {RUNNING, DEAD}
```

`service_registry ⊆ {pid | check_service_alive(pid) == RUNNING}`

每次调用 `check_service` 都会主动维护该不变式：
- 检测到进程已死亡 → 自动从注册表移除
- 输出日志尾部信息给 LLM，用于快速诊断

`start_service` 启动后内置等待窗口期，进程若立即崩溃，直接返回日志，让 LLM 在首轮反向迭代就能定位问题，无需多轮重试排查。

## Done Criteria 分层校验
V1 完成判定依赖「LLM 主观觉得做完」，存在自欺偏差；
V2 定义**分层硬性完成标准**：
1. `start_service` 返回 [ok] — L2 服务启动校验
2. `http_check 主页检测 [ok]` — L1 接口可用性校验
3. `browser_check 模拟用户流程 [ok]` — L3 端到端业务校验
4. 所有注册服务执行 `stop_service` 收尾 — L2 资源清理兜底

## 设计决策记录
### 为什么 browser_check 采用 Console + Network 双通道？
LLM 仅看到 `Failed to load resource` 报错时，无具体请求 URL 无法定位问题根源。
V2 同时监听页面控制台、请求成功/失败日志，主动抓取 4xx/5xx 异常请求，并附带**500 字响应正文预览**。

诊断带宽决定反向迭代质量：文本通道告知「出了什么错」，网络通道解释「为什么出错」。

### 为什么 stop_service 设计为幂等？
避免 LLM 重复调用、服务未注册时报错陷入重试死循环。
幂等设计：无论服务是否存在、是否已停止，多次调用 `stop_service` 最终结果一致，稳定收敛到「服务已下线」终态。

### 为什么用 finally 强制全局清理？
LLM 存在逻辑遗漏、忘记手动停服务；后台进程可能异常逃逸。
通过 `finally` 遍历服务注册表，强制终止所有进程，**根治 V1 进程残留、端口占用问题**。

## V2 边界说明（版本失效约束）
- ✗ 不支持跨会话持久化状态（预留 V3 init/worker 双智能体迭代）
- ✗ 不处理多服务并发资源竞争（预留 V5 Git 协同并行能力）
- ✗ browser_check 仅做功能流程校验，不负责UI视觉美观判定
- ✗ expect_contains 为关键字匹配，非深度语义理解，仍存在关键字命中但业务逻辑错误的场景（L3 天然统计特性，无法在 L1 层级完全闭合）

## 快速运行
```bash
pip install openai python-dotenv requests playwright
playwright install chromium
python H2.py
```
修改 `H2.py` 底部 Prompt 即可自定义任务，也可直接使用默认网页交互测试案例。

## 版本迭代路线
- V0：裸循环 + Bash 基础能力
- V1：形式化 TDD + 工具契约约束
- **V2：L2/L3 分层验证 + 服务状态机（当前版本）**
- V3：init/worker 双智能体 + 上下文压缩
- V4：生成器/评估器双角色架构
- V5：并行任务调度 + Git 版本协同