# -*- coding: utf-8 -*-
"""opencode_tls_clienthello2.py — TCP seq 기반 재조립으로 zen ClientHello 캡처 (2026-10-08)

ClientHello가 다중 TCP 세그먼트(28바이트씩)로 분할됨 → seq 번호로 재조립.
"""
import sys, time
from scapy.all import sniff, IP, TCP

BUFS = {}  # (src, sport, dst) -> {"data": bytes, "seq": int}

def cb(pkt):
    if not (pkt.haslayer(IP) and pkt.haslayer(TCP)):
        return
    ip, tcp = pkt[IP], pkt[TCP]
    if not (ip.dst.startswith("172.65.90.") and tcp.dport == 443 and tcp.payload):
        return
    data = bytes(tcp.payload)
    key = (ip.src, tcp.sport, ip.dst)
    seq = tcp.seq
    if key not in BUFS:
        BUFS[key] = {"data": b"", "seq": seq}
    buf = BUFS[key]
    # seq 기반 이어붙이기
    offset = seq - buf["seq"]
    if offset >= 0:
        if offset > len(buf["data"]):
            # 갭 — 리셋
            BUFS[key] = {"data": data, "seq": seq}
        else:
            buf["data"] = buf["data"][:offset] + data
    else:
        # 앞선 조각 — 앞에 붙임
        buf["data"] = data + buf["data"][-offset:] if offset < 0 else data + buf["data"]
        buf["seq"] = seq
    blob = buf["data"]
    # ClientHello 완성 확인
    if len(blob) >= 5 and blob[0] == 0x16 and blob[1] == 0x03:
        rec = int.from_bytes(blob[3:5], "big")
        if len(blob) >= 5 + rec and blob[5] == 0x01:
            body = blob[5:5+rec]
            print(f"[CH-full] {time.strftime('%H:%M:%S')} rec_len={rec}", flush=True)
            try:
                o = 4 + 2 + 32
                o += 1 + body[o]
                o += 2 + int.from_bytes(body[o:o+2], "big")
                o += 1 + body[o]
                ext_total = int.from_bytes(body[o:o+2], "big")
                o += 2
                end = o + ext_total
                while o + 4 <= end:
                    t = int.from_bytes(body[o:o+2], "big")
                    l = int.from_bytes(body[o+2:o+4], "big")
                    if t == 0:
                        sl = o + 4
                        slen = int.from_bytes(body[sl+2:sl+4], "big")
                        sni = body[sl+4:sl+4+slen].decode("utf-8", "replace")
                        print(f"  SNI: {sni}", flush=True)
                    o += 4 + l
                # 세션 ID 길이, 확장 목록 (JA3 단서)
                o2 = 4 + 2 + 32
                sid_len = body[o2]
                print(f"  session_id_len={sid_len}", flush=True)
                # cipher suites
                o3 = o2 + 1 + sid_len
                cs_len = int.from_bytes(body[o3:o3+2], "big")
                cs = [f"{int.from_bytes(body[o3+2+i*2:o3+4+i*2],'big'):04x}" for i in range(cs_len//2)]
                print(f"  cipher_suites({len(cs)}): {','.join(cs[:12])}", flush=True)
                # 확장
                o4 = o3 + 2 + cs_len
                o4 += 1 + body[o4]
                et = int.from_bytes(body[o4:o4+2], "big")
                o4 += 2
                exts = []
                eend = o4 + et
                while o4 + 4 <= eend:
                    t = int.from_bytes(body[o4:o4+2], "big")
                    l = int.from_bytes(body[o4+2:o4+4], "big")
                    exts.append(f"{t:04x}")
                    o4 += 4 + l
                print(f"  extensions({len(exts)}): {','.join(exts[:25])}", flush=True)
            except Exception as e:
                print(f"  parse err: {e}", flush=True)
            BUFS.pop(key, None)

def main():
    iface = sys.argv[1] if len(sys.argv) > 1 else None
    dur = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    print(f"ClientHello 재조립 캡처 {dur}초", flush=True)
    sniff(iface=iface, prn=cb, timeout=dur, store=False)

if __name__ == "__main__":
    main()