# -*- coding: utf-8 -*-
"""opencode_zen_capture.py — opencode가 zen에 보내는 요청 캡처 (2026-10-08)

mitmproxy 인라인 스크립트:
- opencode.ai/zen 요청의 URL/헤더/바디(부분)를 파일에 기록
- HTTPS도 캡처 (MITM CA 없이는 CONNECT만 보임; CA 설치 후 전체)
"""
import json, os, time

LOG = os.path.join(os.environ.get("TEMP", r"C:\Users\mandu\AppData\Local\Temp"), "zen_capture.jsonl")

def request(flow):
    try:
        host = flow.request.pretty_host
        if "opencode.ai" in host or "zen" in flow.request.path:
            rec = {
                "ts": time.time(),
                "method": flow.request.method,
                "url": f"https://{host}{flow.request.path}",
                "headers": dict(flow.request.headers),
                "body_prefix": flow.request.get_text()[:500] if flow.request.content else "",
            }
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[ZEN] {rec['method']} {rec['url']}", flush=True)
    except Exception as e:
        print(f"[ERR] {e}", flush=True)

def response(flow):
    try:
        host = flow.request.pretty_host
        if "opencode.ai" in host:
            rec = {
                "ts": time.time(),
                "status": flow.response.status_code,
                "headers": dict(flow.response.headers),
                "body_prefix": flow.response.get_text()[:300] if flow.response.content else "",
            }
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass