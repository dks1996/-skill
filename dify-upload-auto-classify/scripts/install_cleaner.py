# -*- coding: utf-8 -*-
"""
核心改造脚本：在 Pipeline 知识库里安装/更新「智能清洗器」，固化分段参数，发布。

幂等：重复运行不会重复插入清洗节点；已有清洗节点则更新其代码和连线。

用法：
    python install_cleaner.py --config config.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dify_client as dc


# ---------------------------------------------------------------- 默认清洗规则
DEFAULT_RULES = {
    "types": [
        {
            "name": "credit_report", "label": "征信报告",
            "keywords": ["征信报告", "信用报告", "贷款余额", "信用记录"],
            "add_subject_prefix": True, "subject_label": "征信主体",
            "subject_regex": "(?:姓名|名称)[\\s:：]*([^\\n，,。]{2,20})",
            "prefix_template": "{subject}的{label}：",
        },
        {"name": "tender", "label": "招标文件",
         "keywords": ["招标文件", "采购", "投标", "中标"], "add_subject_prefix": False},
        {"name": "contract", "label": "合同",
         "keywords": ["合同", "协议", "甲方", "乙方"], "add_subject_prefix": False},
    ],
    "fragment_repair": {
        "min_lines": 20, "short_line_max_chars": 3,
        "short_line_ratio": 0.5, "merge_length": 120,
    },
    "normalize": {
        "collapse_blank_lines": True,
        "strip_line_tail_spaces": True,
        "drop_page_numbers": True,
    },
}


def merge_rules(user_rules: dict) -> dict:
    """用户规则与默认规则合并：用户给了 types 就用用户的，其余补默认。"""
    if not user_rules:
        return dict(DEFAULT_RULES)
    merged = dict(DEFAULT_RULES)
    for k, v in user_rules.items():
        if k.startswith("_"):
            continue
        merged[k] = v
    return merged


# ---------------------------------------------------------------- 生成 Code 节点代码
def render_clean_code(rules: dict) -> str:
    """
    把清洗规则序列化成一段自包含的 Python 代码，写进 Dify Code 节点。
    这段代码只依赖标准库 re，符合 Dify Code 节点的沙箱限制。
    """
    payload = json.dumps(rules, ensure_ascii=False)
    return f'''import re
import json

# 清洗规则（由 skill 从 config.json 注入）
RULES = json.loads({json.dumps(payload, ensure_ascii=False)})
TYPES = RULES.get("types", [])
FRAG = RULES.get("fragment_repair", {{}})
NORM = RULES.get("normalize", {{}})


def detect_type(s):
    for t in TYPES:
        for kw in t.get("keywords", []):
            if kw in s:
                return t
    return None


def repair_fragments(s):
    raw = s.split("\\n")
    min_lines = int(FRAG.get("min_lines", 20))
    short_max = int(FRAG.get("short_line_max_chars", 3))
    ratio = float(FRAG.get("short_line_ratio", 0.5))
    merge_len = int(FRAG.get("merge_length", 120))
    if len(raw) < min_lines:
        return s
    short_count = sum(1 for ln in raw if 0 < len(ln.strip()) <= short_max)
    if short_count / len(raw) <= ratio:
        return s
    buf, merged = "", []
    for ln in raw:
        t = ln.strip()
        if not t:
            if buf:
                merged.append(buf); buf = ""
            continue
        if len(t) <= short_max:
            buf += t
            if len(buf) >= merge_len:
                merged.append(buf); buf = ""
        else:
            if buf:
                merged.append(buf); buf = ""
            merged.append(t)
    if buf:
        merged.append(buf)
    return "\\n".join(merged)


def normalize(s):
    s = s.replace("\\r", "")
    if NORM.get("strip_line_tail_spaces", True):
        s = re.sub(r"[ \\t]+\\n", "\\n", s)
    if NORM.get("collapse_blank_lines", True):
        s = re.sub(r"\\n{{3,}}", "\\n\\n", s)
    s = re.sub(r"[ \\t]{{2,}}", " ", s)
    if NORM.get("drop_page_numbers", True):
        s = re.sub(r"第\\s*\\d+\\s*页\\s*/?\\s*共\\s*\\d+\\s*页", "", s)
        s = re.sub(r"^\\s*\\d{{1,3}}\\s*$", "", s, flags=re.M)
    return s


def add_subject_prefix(s, t):
    m = re.search(t.get("subject_regex", "(?:姓名|名称)[\\\\s:：]*([^\\\\n，,。]{{2,20}})"), s)
    subject = m.group(1).strip() if m else t.get("subject_label", "相关主体")
    label = t.get("label", "文档")
    lines = [ln.strip() for ln in s.split("\\n") if ln.strip()]
    head = lines[0] if lines else ""
    tmpl = t.get("prefix_template", "{{subject}}的{{label}}：")
    prefix = tmpl.replace("{{subject}}", subject).replace("{{label}}", label)
    if subject in head or prefix.rstrip("：:") in head:
        return s
    return prefix + "\\n" + "\\n".join(lines[:400])


def main(text: str):
    s = text or ""
    if not s.strip():
        return {{"result": ""}}
    s = repair_fragments(s)
    s = normalize(s)
    t = detect_type(s)
    if t and t.get("add_subject_prefix"):
        s = add_subject_prefix(s, t)
    if not s.strip():
        s = text or ""
    return {{"result": s.strip()}}
'''


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry-run", action="store_true", help="只生成配置与预览，不写回 Dify")
    args = ap.parse_args()

    cfg = dc.load_config(args.config)
    headers, cookies = dc.load_auth(cfg)
    draft = dc.get_draft(cfg, headers, cookies)
    graph = dc.graph_of(draft)
    nodes, edges = graph["nodes"], graph["edges"]

    found = dc.discover(nodes)
    dc.require(found)
    agg = found["aggregator"]
    chunker = found["chunker"]

    rules = merge_rules(cfg.get("clean_rules", {}))
    code = render_clean_code(rules)

    # 本地先跑一遍代码，确保语法与基本功能正确
    ns = {"re": __import__("re"), "json": json}
    try:
        exec(code, ns)
        probe = ns["main"]("姓名：测试主体\n征信\n" + "信" * 200)["result"]
        assert probe.strip(), "清洗函数返回空"
    except Exception as e:
        raise RuntimeError(f"生成的清洗代码自检失败：{e}")

    # 找到或新建清洗节点
    if found["cleaners"]:
        cleaner = found["cleaners"][0]
        cid = cleaner["id"]
        print(f"[更新] 已有智能清洗节点：{cid}")
    else:
        import uuid
        cid = "clean-" + uuid.uuid4().hex[:12]
        cleaner = {
            "id": cid,
            "type": "custom",
            "position": {"x": 620, "y": 300},
            "positionAbsolute": {"x": 620, "y": 300},
            "width": 242, "height": 88, "zIndex": 0,
            "sourcePosition": "right", "targetPosition": "left",
            "data": {
                "type": "code", "title": "智能清洗器",
                "desc": "按文件类型自动识别并清洗：修复PDF碎片、规范空白、按类型补主体前缀",
                "code_language": "python3", "selected": False,
            },
        }
        nodes.append(cleaner)
        print(f"[新建] 智能清洗节点：{cid}")

    cdata = cleaner["data"]
    cdata["code"] = code
    cdata["variables"] = [{"variable": "text", "value_selector": [agg["id"], "output"]}]
    cdata.setdefault("outputs", {"result": {"type": "string", "children": None}})

    # 改连线：删除 聚合器→分段器，改为 聚合器→清洗器→分段器
    edges[:] = [e for e in edges
                if not (e.get("source") == agg["id"] and e.get("target") == chunker["id"])]
    if not any(e.get("source") == agg["id"] and e.get("target") == cid for e in edges):
        edges.append(dc.new_edge(agg["id"], cid))
    if not any(e.get("source") == cid and e.get("target") == chunker["id"] for e in edges):
        edges.append(dc.new_edge(cid, chunker["id"]))

    # 分段器输入改为引用清洗器结果：必须用 variable 类型 + selector 数组
    tp = chunker["data"].setdefault("tool_parameters", {})
    tp["input_variable"] = {"type": "variable", "value": [cid, "result"]}

    # 固化分段参数：共享变量 rag.shared.* 未初始化会报 Variable does not exist
    cp = cfg.get("chunk_params", {})
    tp["delimiter"] = {"type": "constant", "value": cp.get("delimiter", "\n\n")}
    tp["max_chunk_length"] = {"type": "constant", "value": int(cp.get("max_chunk_length", 800))}
    tp["chunk_overlap_length"] = {"type": "constant", "value": int(cp.get("chunk_overlap_length", 80))}
    tp["replace_consecutive_spaces_newlines_tabs"] = {
        "type": "constant", "value": bool(cp.get("replace_consecutive_spaces_newlines_tabs", True))}
    tp["delete_all_urls_and_email_addresses"] = {
        "type": "constant", "value": bool(cp.get("delete_all_urls_and_email_addresses", False))}

    # 处理 Dify Extractor 插件的 FILES_URL 问题：改连到内置文档提取器
    plugin_ext = [n for n in found["extractors"] if "dify" in n["data"].get("title", "").lower()]
    builtin_ext = [n for n in found["extractors"] if "dify" not in n["data"].get("title", "").lower()]
    if plugin_ext and builtin_ext:
        plugin_ids = {n["id"] for n in plugin_ext}
        builtin_id = builtin_ext[0]["id"]
        for e in edges:
            if e.get("target") in plugin_ids:
                e["target"] = builtin_id
        edges[:] = [e for e in edges if e.get("source") not in plugin_ids]
        nodes[:] = [n for n in nodes if n["id"] not in plugin_ids]
        for n in nodes:
            if n["id"] == agg["id"]:
                n["data"]["variables"] = [[builtin_id, "text"]]
        print(f"[修复] Dify Extractor 插件改连到内置文档提取器：{builtin_id}")

    print(f"[连线] 聚合器({agg['id']}) → 清洗器({cid}) → 分段器({chunker['id']}) → 知识库")
    print(f"[参数] 分段已固化：{tp['max_chunk_length']['value']} / {tp['chunk_overlap_length']['value']}")

    if args.dry_run:
        print("[dry-run] 未写回 Dify。")
        return

    dc.save_draft(cfg, headers, cookies, graph, draft.get("features", {}), draft.get("hash"))
    print("[保存] 草稿已保存")
    dc.publish(cfg, headers, cookies)
    print("[发布] 流水线已发布，改造完成。")


if __name__ == "__main__":
    main()
