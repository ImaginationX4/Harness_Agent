# Agent Harness

一个本地 AI Agent 执行框架，支持服务管理、多层验证和知识库检索。

---

## 文件结构

```
.
├── config.py          # API 密钥 / 模型 / BASE_URL（自行填写）
├── harness.py         # 协调层：tool dispatch + agent 主循环
├── models.py          # 数据类型：ServiceState, ServiceInfo
├── service_ops.py     # 服务生命周期：start / stop / check / list / cleanup
├── verifier.py        # 无状态验证：run_command / http_check / browser_check
├── tools_def.py       # 工具 schema 列表（LLM 可调用的工具定义）
├── search_kb.py       # 知识库检索：对本地 .md 文件做关键词搜索
├── knowledge/         # 知识库目录（放你的 .md 文件）
└── test_search_kb.py  # search_kb 的 pytest 测试
```

---

## 快速开始

**安装依赖**

```bash
pip install openai requests playwright python-dotenv
playwright install chromium
```

**配置 `config.py`**

```python
API_KEY  = "your-key"
MODEL_ID = "your-model-id"
BASE_URL = "https://..."
```

**放入知识库**（可选）

把 `.md` 文件放进 `knowledge/` 目录，agent 会在需要时自动检索。

**运行**

```bash
python harness.py
```

或在代码里调用：

```python
import harness
from pathlib import Path

harness.KB_DIR = Path("./knowledge")   # 可选：覆盖知识库路径
msgs = harness.run_agent("做一个可以互动的网页")
```

---

## 工具列表

| 工具 | 层级 | 说明 |
|---|---|---|
| `run_command` | — | 执行短命令，返回 stdout/stderr |
| `start_service` | — | 后台启动服务，必须声明 `port` |
| `stop_service` | — | 按 service_id 停服务 |
| `check_service` | L0 | 检查进程是否存活（弱验证） |
| `list_services` | — | 列出所有运行中的服务和端口 |
| `http_check` | L1/L2 | HTTP 请求 + 关键词断言 |
| `browser_check` | L3 | 无头浏览器，模拟用户交互 |
| `search_kb` | — | 检索本地知识库，返回相关段落 |

**验证层级**：`check_service` < `http_check` < `browser_check`，任务完成前三层都要过。

---

## 知识库检索

`search_kb` 对 `knowledge/` 下的所有 `.md` 文件做关键词检索。按 `##` / `###` 标题切块，标题命中权重高于正文。

```python
from search_kb import search_kb
results = search_kb("RAG memory", k=5)
# results: list[Chunk]，每个 Chunk 有 source / heading / text / score
```

**切换知识库路径**：

```python
import harness, search_kb
from pathlib import Path
harness.KB_DIR = Path("/your/kb")
```

---
