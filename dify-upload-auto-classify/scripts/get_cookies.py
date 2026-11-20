# -*- coding: utf-8 -*-
"""
辅助导出 Dify 登录 Cookie：打开浏览器让用户登录，自动保存 cookies.json。

用法：python get_cookies.py --url http://<dify地址> --out cookies.json
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="Dify 访问根地址，如 http://dify.example.com:8080")
    ap.add_argument("--out", default="cookies.json")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("缺少依赖，请先运行：python -m pip install playwright && python -m playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        print(f"正在打开 {args.url}，请在浏览器里登录 Dify 管理后台...")
        page.goto(args.url.rstrip("/"), wait_until="domcontentloaded")
        input("登录并看到控制台首页后，回到这里按回车继续...")
        # 等待 cookie 就绪（最多再给 10 秒）
        page.wait_for_timeout(3000)
        cookies = ctx.cookies()
        state = {"cookies": cookies}
        Path(args.out).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        names = [c["name"] for c in cookies]
        print(f"已导出 {len(cookies)} 个 Cookie 到 {args.out}")
        print("其中关键项：", [n for n in names if "token" in n.lower() or "csrf" in n.lower()])
        if "access_token" not in names:
            print("⚠ 未发现 access_token，请确认确实登录成功后重试。")
        browser.close()


if __name__ == "__main__":
    main()
