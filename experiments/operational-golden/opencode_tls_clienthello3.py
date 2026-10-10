# -*- coding: utf-8 -*-
"""opencode_tls_clienthello3.py — seq 역순 캡처 대응 재조립 (2026-10-08)

scapy가 다중 연결 패킷을 seq 역순으로 전달 → 세그먼트를 seq 기준 사전에 쌓고,
연결의 첫 조각(0x16 헤더) 기준으로 정렬 후 재조립.
"""
import sys, time
from scapy.all import sniff, IP, TCP

FRAGS = {}  # (src,sport,dst) -> {seq: bytes}

def cb(pkt):
    if not (pkt.haslayer(IP) and pkt.haslayer(TCP)):
        return
    ip, tcp = pkt[IP], pkt[TCP]
    if not (ip.dst.startswith("172.65.90.") and tcp.dport == 443 and tcp.payload):
        return
    data = bytes(tcp.payload)
    key = (ip.src, tcp.sport, ip.dst)
    FRAGS.setdefault(key, {})[tcp.seq] = data

    blob = try_assemble(key)
    if blob:
        rec = int.from_bytes(blob[3:5], "big")
        if len(blob) >= 5 + rec and blob[5] == 0x01:
            body = blob[5:5+rec]
            print(f"[CH-full] {time.strftime('%H:%M:%S')} {ip.dst} rec_len={rec}", flush=True)
            try:
                o = 4 + 2 + 32
                o += 1 + body[o]
                o += 2 + int.from_bytes(body[o:o+2], "big")
                o += 1 + body[o]
                sni = "?"
                ext_total = int.from_bytes(body[o:o+2], "big") if o+2 <= len(body) else 0
                o += 2
                end = o + ext_total
                while o + 4 <= end:
                    t = int.from_bytes(body[o:o+2], "big")
                    l = int.from_bytes(body[o+2:o+4], "big")
                    if t == 0:
                        sl = o + 4
                        slen = int.from_bytes(body[sl+2:sl+4], "big")
                        sni = body[sl+4:sl+4+slen].decode("utf-8", "replace")
                    o += 4 + l
                print(f"  SNI: {sni}", flush=True)
                # 세션ID/암호화폐 모음/확장 (JA3 단서)
                o2 = 4 + 2 + 32
                sid_len = body[o2]
                o3 = o2 + 1 + sid_len
                cs_len = int.from_bytes(body[o3:o3+2], "big")
                cs = [f"{int.from_bytes(body[o3+2+i*2:o3+4+i*2],'big'):04x}" for i in range(cs_len//2)][:15]
                print(f"  sid_len={sid_len} cipher_suites({len(cs)}): {','.join(cs)}", flush=True)
                o4 = o3 + 2 + cs_len
                o4 += 1 + body[o4]
                et = int.from_bytes(body[o4:o4+2], "big")
                o4 += 2
                exts = []
                eend = o4 + et
                while o4 + 4 <= eend:
                    t = int.from_bytes(body[o4:o4+2], "big")
                    l = int.from_bytes(body[o4+2:o4+4], "big")
                    exts.append(f"{t:04x}({l})")
                    o4 += 4 + l
                print(f"  extensions({len(exts)}): {','.join(exts[:25])}", flush=True)
            except Exception as e:
                print(f"  parse err: {e}", flush=True)
            FRAGS.pop(key, None)

def try_assemble(key):
    """seq 사전을 정렬해 연속 블록이면 병합, 첫 바이트 0x16이면 반환"""
    frags = FRAGS.get(key)
    if not frags:
        return None
    seqs = sorted(frags)
    # 첫 조각이 TLS 헤더(0x16)인지
    first_data = frags[seqs[0]]
    if first_data[0] != 0x16:
        # 헤더 아닌 조각으로 시작 — 아직 첫 조각 대기 중
        return None
    # 연속성 확인: 마지막 seq + len == 다음 seq
    blob = b""
    expect = None
    for s in seqs:
        if expect is not None and s != expect:
            return None  # 갭 — 아직 도착 안 함
        blob += frags[s]
        expect = s + len(frags[s])
    return blob

def main():
    iface = sys.argv[1] if len(sys.argv) > 1 else None
    dur = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    print(f"ClientHello 재조립 v3 {dur}초", flush=True)
    sniff(iface=iface, prn=cb, timeout=dur, store=False)

if __name__ == "__main__":
    main()