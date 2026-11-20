# -*- coding: utf-8 -*-
"""
Dify 控制台 API 通用客户端。

只负责四件通用能力：认证、读草稿、存草稿、发布；外加按节点类型/标题智能发现节点。
不包含任何环境相关的地址、知识库 ID、节点 ID 硬编码——全部从配置或草稿动态获得。

作者注：Dify 1.20.0 的 console API 连 GET 都要带 X-CSRF-Token，否则 401。
"""
import json
import os
import sys
from pathlib import Path


class AuthError(RuntimeError):
    """缺少或无效的认证信息。"""


class ApiError(RuntimeError):
    """Dify 接口返回非预期状态。"""


# ---------------------------------------------------------------- 认证
def load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"配置文件不存在：{path}（请复制 assets/config.example.json 为 config.json）")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    for key in ("dify_base_url", "dataset_id", "pipeline_id"):
        if not cfg.get(key) or str(cfg[key]).startswith("把这里换成"):
            raise ValueError(f"config.json 的 {key} 还未填写真实值")
    cfg["dify_base_url"] = cfg["dify_base_url"].rstrip("/")
    return cfg


def load_auth(cfg: dict):
    """返回 (headers, cookies)。cookie 来自 cookies_file 或环境变量。"""
    cookies = {}
    cfile = cfg.get("cookies_file")
    if cfile and Path(cfile).exists():
        raw = json.loads(Path(cfile).read_text(encoding="utf-8"))
        # 兼容 playwright storage_state({"cookies":[...]}) 与纯 {name:value} 两种格式
        if isinstance(raw, dict) and "cookies" in raw:
            cookies = {c["name"]: c["value"] for c in raw["cookies"]}
        elif isinstance(raw, dict):
            cookies = raw
    token = os.environ.get("DIFY_ACCESS_TOKEN") or cookies.get("access_token")
    csrf = os.environ.get("DIFY_CSRF_TOKEN") or cookies.get("csrf_token")
    if not token or not csrf:
        raise AuthError(
            "缺少 access_token 或 csrf_token。请用 scripts/get_cookies.py 导出 cookies.json，"
            "或设置环境变量 DIFY_ACCESS_TOKEN / DIFY_CSRF_TOKEN。"
        )
    headers = {
        "Authorization": "Bearer " + token,
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    return headers, cookies


def _requests():
    try:
        import requests
        return requests
    except ImportError:
        raise RuntimeError("缺少依赖 requests，请先运行：python -m pip install requests")


# ---------------------------------------------------------------- 草稿读写
def draft_url(cfg: dict) -> str:
    return (f"{cfg['dify_base_url']}/console/api/rag/pipelines/"
            f"{cfg['pipeline_id']}/workflows/draft")


def publish_url(cfg: dict) -> str:
    return (f"{cfg['dify_base_url']}/console/api/rag/pipelines/"
            f"{cfg['pipeline_id']}/workflows/publish")


def get_draft(cfg: dict, headers: dict, cookies: dict) -> dict:
    r = _requests().get(draft_url(cfg), headers=headers, cookies=cookies, timeout=30)
    if r.status_code != 200:
        raise ApiError(f"读取草稿失败 {r.status_code}：{r.text[:300]}")
    return r.json()


def save_draft(cfg, headers, cookies, graph, features, hash_value) -> dict:
    body = {"graph": graph, "features": features, "hash": hash_value}
    r = _requests().post(
        draft_url(cfg), headers=headers, cookies=cookies,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=60,
    )
    if r.status_code == 409:
        raise ApiError("草稿版本冲突（409），说明有其他人改过流水线，请重新运行脚本（会读取最新 hash）")
    if r.status_code != 200:
        raise ApiError(f"保存草稿失败 {r.status_code}：{r.text[:300]}")
    return r.json()


def publish(cfg: dict, headers: dict, cookies: dict) -> dict:
    r = _requests().post(
        publish_url(cfg), headers=headers, cookies=cookies,
        data=b"{}", timeout=60,
    )
    if r.status_code not in (200, 201):
        raise ApiError(f"发布失败 {r.status_code}：{r.text[:300]}")
    return r.json()


def graph_of(draft: dict) -> dict:
    """从草稿取出可回存的 graph（去掉 viewport 之外的冗余字段也能工作，这里全保留）。"""
    g = draft["graph"]
    return {
        "nodes": g["nodes"],
        "edges": g["edges"],
        "viewport": g.get("viewport", {"x": 0, "y": 0, "zoom": 1}),
    }


# ---------------------------------------------------------------- 节点发现
def find_nodes(nodes, *, types=None, title_has=None, tool_has=None):
    """按 type/title/tool_name 过滤节点，匹配均小写包含。"""
    hits = []
    for n in nodes:
        d = n.get("data", {})
        t = str(d.get("type", "")).lower()
        title = str(d.get("title", "")).lower()
        tool = str(d.get("tool_name", "")).lower()
        if types and not any(x.lower() in t for x in types):
            continue
        if title_has and not any(x.lower() in title for x in title_has):
            continue
        if tool_has and not any(x.lower() in tool for x in tool_has):
            continue
        hits.append(n)
    return hits


def discover(nodes):
    """
    智能发现关键节点。不同 Dify 版本的 title 可能不同，故用多重匹配。
    返回 dict：aggregator / chunker / knowledge_base / extractors / if_else / cleaners
    """
    def first(lst):
        return lst[0] if lst else None

    agg = first(find_nodes(nodes, types=["aggregator", "variable-aggregator"])
                or find_nodes(nodes, title_has=["aggregator", "聚合"]))
    chunker = first(find_nodes(nodes, tool_has=["chunk"])
                    or find_nodes(nodes, title_has=["chunker", "分段"]))
    kb = first(find_nodes(nodes, title_has=["knowledge base", "知识库"])
               or find_nodes(nodes, types=["knowledge-base", "dataset"]))
    extractors = find_nodes(nodes, title_has=["extract", "提取"])
    if_else = find_nodes(nodes, types=["if-else", "condition", "if"])
    cleaners = find_nodes(nodes, title_has=["智能清洗", "auto clean"])

    return {
        "aggregator": agg,
        "chunker": chunker,
        "knowledge_base": kb,
        "extractors": extractors,
        "if_else": if_else,
        "cleaners": cleaners,
    }


def new_edge(src_id, tgt_id, source_handle="source") -> dict:
    import uuid
    return {
        "id": uuid.uuid4().hex,
        "source": src_id,
        "sourceHandle": source_handle,
        "target": tgt_id,
        "targetHandle": "target",
        "type": "custom",
        "data": {"sourceType": "custom"},
    }


def require(nodes_found: dict, keys=("aggregator", "chunker", "knowledge_base")):
    missing = [k for k in keys if not nodes_found.get(k)]
    if missing:
        raise ValueError(
            "流水线里没找到这些关键节点：" + ", ".join(missing)
            + "。请用 inspect_pipeline.py 查看全部节点，并按需调整 dify_client.discover() 的匹配规则。"
        )
