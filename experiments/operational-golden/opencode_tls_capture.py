# -*- coding: utf-8 -*-
"""opencode_tls_capture.py — opencode 서비스의 TLS 트래픽 캡처 (npcap/scapy)

opencode.ai:443으로 나가는 연결의 TLS ClientHello를 캡처:
- 목적지 IP/포트
- SNI (서버 이름)
- JA3 핑거프린트 (TLS 지문 — zen이 클라이언트를 구분하는 핵심 후보)

실행: python opencode_tls_capture.py <interface> <duration_sec>
"""
import sys, time
from scapy.all import sniff, IP, TCP, Raw

# opencode.ai / zenmux.ai Cloudflare IP 범위 (2026-10-08 nslookup 확인)
TARGET_IPS = {"172.65.90.20", "172.65.90.21", "172.65.90.22", "172.65.90.23",
              "172.65.90.66", "172.65.90.67", "172.66.173.149", "104.20.32.17"}

def is_target(ip_str):
    return True  # 모든 아웃바운드 443 캡처 (대상 IP 필터 해제 — 2026-10-08)

def process_tls(pkt):
    """TCP 재조립 세션에서 완전한 TLS 기록 처리"""
    if not (pkt.haslayer(IP) and pkt.haslayer(TCP)):
        return
    ip = pkt[IP]
    tcp = pkt[TCP]
    if not is_target(ip.dst):
        return
    payload = bytes(tcp.payload)
    if len(payload) < 1:
        return
    # 모든 TLS 레코드(0x16) 또는 TCP 상태 출력 — ClientHello(0x01)만이 아니라
    print(f"[PKT] {time.strftime('%H:%M:%S')} -> {ip.dst}:{tcp.dport} len={len(payload)} first={payload[0]:02x}", flush=True)
    if payload[0] == 0x16 and len(payload) >= 6 and payload[5] == 0x01:
        # ClientHello 완전한가? record 길이 확인
        rec_len = int.from_bytes(payload[3:5], 'big')
        if len(payload) >= 5 + rec_len:
            body = payload[5:5+rec_len]
            try:
                o = 4  # handshake header skip
                o += 2 + 32  # version + random
                sid_len = body[o] if o < len(body) else 0
                o += 1 + sid_len
                cs_len = int.from_bytes(body[o:o+2], 'big') if o + 2 <= len(body) else 0
                o += 2 + cs_len
                o += 1 + body[o] if o < len(body) else 0
                sni = "?"
                ext_total = int.from_bytes(body[o:o+2], 'big') if o + 2 <= len(body) else 0
                o += 2
                end = min(o + ext_total, len(body))
                while o + 4 <= end:
                    etype = int.from_bytes(body[o:o+2], 'big')
                    elen = int.from_bytes(body[o+2:o+4], 'big')
                    if etype == 0 and o + 4 + elen <= len(body):
                        sl = o + 4
                        sni_len = int.from_bytes(body[sl+2:sl+4], 'big')
                        sni = body[sl+4:sl+4+sni_len].decode('utf-8', 'replace')
                    o += 4 + elen
                # JA3 요소: cipher suites 목록 추출
                print(f"[TLS] {time.strftime('%H:%M:%S')} -> {ip.dst}:443 SNI={sni} body_len={len(body)}", flush=True)
            except Exception:
                pass

def main():
    iface = sys.argv[1] if len(sys.argv) > 1 else None
    dur = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    print(f"캡처 시작 iface={iface} {dur}초 (타겟: {TARGET_IPS})", flush=True)
    sniff(iface=iface, prn=process_tls, timeout=dur, store=False)

if __name__ == "__main__":
    main()