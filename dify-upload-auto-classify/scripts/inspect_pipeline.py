# -*- coding: utf-8 -*-
"""
探测流水线结构：打印所有节点与自动识别出的关键节点，改造前先跑这个确认识别正确。

用法：python inspect_pipeline.py --config config.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dify_client as dc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--list", action="store_true", help="仅打印 pipeline_id 提示后退出")
    args = ap.parse_args()

    cfg = dc.load_config(args.config)
    if args.list:
        print("pipeline_id 就在知识库流水线页面的 URL 里：")
        print("  http://<dify地址>/datasets/<dataset_id>/pipeline")
        print("当前 config.json 中的 pipeline_id =", cfg["pipeline_id"])
        return

    headers, cookies = dc.load_auth(cfg)
    draft = dc.get_draft(cfg, headers, cookies)
    nodes = draft["graph"]["nodes"]
    edges = draft["graph"]["edges"]

    print("=== 全部节点 ===")
    for n in nodes:
        d = n.get("data", {})
        print(f"  {n['id']:<28} type={str(d.get('type','')):<20} title={d.get('title','')}")

    found = dc.discover(nodes)
    print("\n=== 自动识别的关键节点 ===")
    for key in ("aggregator", "chunker", "knowledge_base"):
        node = found.get(key)
        print(f"  {key:<16}: {node['id'] if node else '未识别 ⚠'}")

    print(f"  extractors      : {[n['id'] for n in found['extractors']]}")
    print(f"  if_else         : {[n['id'] for n in found['if_else']]}")
    print(f"  cleaners(已装)  : {[n['id'] for n in found['cleaners']]}")

    chunker = found.get("chunker")
    if chunker:
        print("\n=== 分段器当前参数 ===")
        print(json.dumps(chunker["data"].get("tool_parameters", {}),
                         ensure_ascii=False, indent=2))

    print("\n=== 连线 ===")
    for e in edges:
        print(f"  {e.get('source')} -( {e.get('sourceHandle','')} )-> {e.get('target')}")

    print("\n=== 共享变量 ===")
    for v in draft.get("rag_pipeline_variables", []):
        print(f"  {v.get('variable')} = {v.get('default_value')!r}")


if __name__ == "__main__":
    main()
