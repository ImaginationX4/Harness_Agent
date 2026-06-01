"""search_kb — 对已有 markdown 知识库的无状态只读检索 (L1)。

契约 (SDD D 层):
  in_type  : (query: str, k: int = 5)
  out_type : list[Chunk]


分叉点决议: ①A 按 ## / ### 标题切块  ②A 关键词命中计数(标题加权)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# 语料 K：固定的知识库目录(隐含参数,不进函数签名)。测试通过 monkeypatch 覆盖。
KB_DIR = Path(__file__).parent / "knowledge"

# 标题行：1-6 个 # 后跟空白
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# 分词：按非字母数字(含中文)切分,空白与标点都算分隔
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

_HEADING_WEIGHT = 3  # 标题命中比正文命中权重高


@dataclass
class Chunk:
    source: str   # 来源 .md 文件路径
    heading: str  # 该块的标题(首块可能为 "")
    text: str     # 块正文
    score: float  # 相关度分


def _split_md(text: str) -> list[tuple[str, str]]:
    """把一份 markdown 切成 (heading, body) 块。标题行开启新块。"""
    chunks: list[tuple[str, str]] = []
    heading = ""
    body: list[str] = []
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            if heading or "".join(body).strip():
                chunks.append((heading, "\n".join(body).strip()))
            heading = m.group(2).strip()
            body = []
        else:
            body.append(line)
    if heading or "".join(body).strip():
        chunks.append((heading, "\n".join(body).strip()))
    return chunks


def _tokenize(s: str) -> list[str]:
    return _TOKEN.findall(s.lower())


def _score(query_tokens: list[str], heading: str, body: str) -> int:
    if not query_tokens:
        return 0
    body_tokens = _tokenize(body)
    head_tokens = _tokenize(heading)
    score = 0
    for qt in query_tokens:
        score += body_tokens.count(qt)
        score += _HEADING_WEIGHT * head_tokens.count(qt)
    return score


def search_kb(query: str, k: int = 5) -> list[Chunk]:
    query_tokens = _tokenize(query)
    if not query_tokens:          # 空/纯空白/纯标点 query → R.deny
        return []

    results: list[Chunk] = []
    for md in sorted(KB_DIR.rglob("*.md")):
        try:
            content = md.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for heading, body in _split_md(content):
            s = _score(query_tokens, heading, body)
            if s > 0:             # INV4 命中才返
                results.append(Chunk(str(md), heading, body, float(s)))

    results.sort(key=lambda c: c.score, reverse=True)  # INV2 分降序
    return results[:k]                                  # INV3 容量界