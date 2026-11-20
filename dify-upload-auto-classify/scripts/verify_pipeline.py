# -*- coding: utf-8 -*-
"""
端到端验证：上传一个"每行一个字符"的碎片测试文件，等待索引完成，检查分段结果。
若碎片被合并成少量正常段落，说明清洗流水线生效。

用法：python verify_pipeline.py --config config.json --file sample_fragment.txt
也可不带 --file，脚本会自动生成一个碎片测试文件。
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dify_client as dc


def make_fragment_file(path: str):
    sample = "姓名：测试主体\n个人征信报告\n贷款余额两笔\n信息显示正常"
    frag = "\n".join(list(sample.replace("\n", "")))
    Path(path).write_text(frag, encoding="utf-8")
    print(f"已生成碎片测试文件：{path}（{len(frag.splitlines())} 行，每行 1 字符）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--file", default=None)
    ap.add_argument("--name", default="自动分类流水线测试", help="上传后显示的文档名")
    args = ap.parse_args()

    cfg = dc.load_config(args.config)
    headers, cookies = dc.load_auth(cfg)
    requests = dc._requests()
    base = cfg["dify_base_url"]
    ds = cfg["dataset_id"]

    fp = args.file or cfg.get("test_file") or "./sample_fragment.txt"
    if not Path(fp).exists():
        make_fragment_file(fp)

    # 1) 上传文件到 files 接口（console 侧）
    with open(fp, "rb") as f:
        r = requests.post(
            f"{base}/console/api/files/upload", headers=headers, cookies=cookies,
            files={"file": (Path(fp).name, f, "text/plain")}, timeout=60,
        )
    if r.status_code not in (200, 201):
        raise SystemExit(f"上传文件失败 {r.status_code}：{r.text[:300]}")
    print("[上传] 成功")

    # 2) 触发文档处理：优先用界面同源的 datasets 处理接口
    file_id = r.json().get("id")
    payload = {
        "name": args.name,
        "indexing_technique": "economy",
        "file_ids": [file_id] if file_id else [],
    }
    r2 = requests.post(
        f"{base}/console/api/datasets/{ds}/documents/process",
        headers=headers, cookies=cookies, json=payload, timeout=120,
    )
    if r2.status_code not in (200, 201):
        print("⚠ 自动处理接口未成功：", r2.status_code, r2.text[:200])
        print("请在控制台手工上传该文件，然后运行本脚本的 --check-only 模式查看分段。")
        return
    print("[处理] 已触发")

    # 3) 轮询文档状态并查看分段
    doc_api = f"{base}/console/api/datasets/{ds}/documents"
    doc_id = None
    for _ in range(30):
        data = requests.get(doc_api, headers=headers, cookies=cookies,
                            params={"page": 1, "limit": 20, "sort": "-created_at"}, timeout=30).json()
        hits = [d for d in data.get("data", []) if d.get("name") == args.name]
        if hits:
            doc_id = hits[0]["id"]
            status = hits[0].get("indexing_status")
            print(f"[状态] {status}")
            if status in ("completed", "available", "error"):
                if status == "error":
                    print("⚠ 索引失败：", hits[0].get("error"))
                break
        time.sleep(2)

    if not doc_id:
        raise SystemExit("未找到刚上传的文档，请到控制台确认。")

    seg_api = f"{doc_api}/{doc_id}/segments"
    seg = requests.get(seg_api, headers=headers, cookies=cookies,
                       params={"page": 1, "limit": 100}, timeout=30).json()
    total = seg.get("total")
    print(f"\n=== 分段结果：共 {total} 段 ===")
    for i, s in enumerate(seg.get("data", [])[:5]):
        content = s.get("content", "")
        print(f"--- 段 {i+1}（长度 {len(content)}）")
        print(content[:200].replace("\n", " "))
    if total and total <= 5:
        print("\n✅ 碎片文件被合并成少量正常段落，清洗流水线生效。")
    else:
        print("\n⚠ 分段数量偏多，请检查清洗器是否已发布、分段参数是否已固化。")


if __name__ == "__main__":
    main()
