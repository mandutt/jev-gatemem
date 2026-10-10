# -*- coding: utf-8 -*-
"""opencode_tls_clienthello.py — TCP 재조립으로 opencode의 ClientHello/SNI 캡처

opencode 서비스(172.65.90.x:443)의 TLS ClientHello를 TCP 스트림 재조립으로 추출.
SNI와 JA3(암호화폐 모음) 확인 — zen 게이트의 클라이언트 식별 단서.
"""
import sys, time
from scapy.all import sniff, IP, TCP

# 연결별 버퍼 (src_port -> bytes)
BUFS = {}
LAST = {}

def proc(pkt):
    if not (pkt.haslayer(IP) and pkt.haslayer(TCP)):
        return
    ip = pkt[IP]
    tcp = pkt[TCP]
    # 디버그: 모든 outbound 443 출력 (필터 문제 확인)
    if tcp.dport != 443:
        return
    if not tcp.payload:
        return
    if ip.dst.startswith("172.65."):
        print(f"[ZEN] {time.strftime('%H:%M:%S')} {ip.src}->{ip.dst}:443 len={len(bytes(tcp.payload))}", flush=True)
    data = bytes(tcp.payload)
    key = (ip.src, tcp.sport, ip.dst, tcp.dport)
    BUFS[key] = BUFS.get(key, b"") + data
    buf = BUFS[key]
    now = time.time()
    if now - LAST.get(key, 0) > 5 or len(BUFS) > 200:
        # 오래된 연결 정리
        for k in [k for k, ts in list(LAST.items()) if now - ts > 10]:
            BUFS.pop(k, None)
            LAST.pop(k, None)
    LAST[key] = now
    # ClientHello 완성 확인 (TLS 레코드 헤더: 16 03 xx xx xx)
    if len(buf) >= 5 and buf[0] == 0x16:
        rec_len = int.from_bytes(buf[3:5], "big")
        if len(buf) >= 5 + rec_len and buf[5] == 0x01:
            print(f"[CH] {time.strftime('%H:%M:%S')} {ip.dst}:443 rec_len={rec_len}", flush=True)
            # SNI
            body = buf[5:5+rec_len]
            try:
                o = 4 + 2 + 32
                o += 1 + body[o]
                o += 2 + int.from_bytes(body[o:o+2], "big")
                o += 1 + body[o]
                ext_total = int.from_bytes(body[o:o+2], "big")
                o += 2
                end = o + ext_total
                sni = "?"
                while o + 4 <= end:
                    t = int.from_bytes(body[o:o+2], "big")
                    l = int.from_bytes(body[o+2:o+4], "big")
                    if t == 0:
                        sl = o + 4
                        slen = int.from_bytes(body[sl+2:sl+4], "big")
                        sni = body[sl+4:sl+4+slen].decode("utf-8", "replace")
                        print(f"  SNI: {sni}", flush=True)
                    o += 4 + l
                # session_id 길이 (JA3 요소 첫 부분)
                o2 = 4 + 2 + 32
                print(f"  session_id_len={body[o2]}", flush=True)
                # 확장 전체(순서) 프린트
                o3 = 4 + 2 + 32
                o3 += 1 + body[o3]
                o3 += 2 + int.from_bytes(body[o3:o3+2], "big")
                o3 += 1 + body[o3]
                extt = int.from_bytes(body[o3:o3+2], "big")
                o3 += 2
                exts = []
                eend = o3 + extt
                while o3 + 4 <= eend:
                    t = int.from_bytes(body[o3:o3+2], "big")
                    l = int.from_bytes(body[o3+2:o3+4], "big")
                    exts.append(f"{t:04x}({l})")
                    o3 += 4 + l
                print(f"  extensions: {', '.join(exts[:20])}", flush=True)
            except Exception as e:
                print(f"  parse err: {e}", flush=True)
            BUFS.pop(key, None)
            LAST.pop(key, None)

def main():
    iface = sys.argv[1] if len(sys.argv) > 1 else None
    dur = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    print(f"ClientHello 캡처 {dur}초 iface={iface}", flush=True)
    sniff(iface=iface, prn=proc, timeout=dur, store=False)

if __name__ == "__main__":
    main()