"""Experiential Labs 키 라운드로빈 레졸버 (실험 스크립트 공용)

- EXPLABS_API_KEY  : 기존 primary (변경 없음 — 기존 코드·데몬 호환)
- EXPLABS_API_KEY2 : 선택 secondary (사용자가 setx로 직접 등록)
- 해석 규칙: os.environ → HKCU\\Environment 레지스트리 순 (기존 resolve_key와 동일)
- 키 값은 절대 출력하지 않음 (길이/접두 4자만 표시)
"""
import os
import threading
import winreg

_NAMES = ("EXPLABS_API_KEY", "EXPLABS_API_KEY2")


def _resolve(name):
    v = os.environ.get(name, "")
    if not v:
        try:
            hk = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
            try:
                val, _ = winreg.QueryValueEx(hk, name)
                if val:
                    v = val
            finally:
                winreg.CloseKey(hk)
        except FileNotFoundError:
            pass
    return v.strip().strip('"')


def get_keys():
    """존재하는 키 목록 (1~2개, 순서 유지)"""
    return [k for k in (_resolve(n) for n in _NAMES) if k]


def get_key_names():
    """존재하는 키의 환경변수 이름 목록 (로깅용)"""
    return [n for n in _NAMES if _resolve(n)]


class SmartRotator:
    """429/소진 인지 키 로테이터.

    - ``next()``: 다음 호출에 사용할 키 반환. last_cost>0 (크레딧 과금) 감지 시
      해당 키를 제외하고 다른 키로 이동.
    - ``on_429()``: 429 발생 시 즉시 다른 키로 전환 (대기 없이 재시도용).
    - 스레드 안전 (RLock).
    """

    def __init__(self):
        self._lock = threading.RLock()
        self.keys = get_keys()
        self.names = get_key_names()
        self.exhausted = set()   # 무료 소진(크레딧 과금)으로 제외된 키 (이름)
        self.i = 0               # 현재 라운드로빈 인덱스
        self.last_cost = None    # 마지막 요청의 usage.cost
        self.last_key = None     # 마지막 사용 키 이름

    def _active(self):
        """사용 가능한 (이름, 키) 목록"""
        return [(n, k) for n, k in zip(self.names, self.keys) if n not in self.exhausted]

    def next(self):
        with self._lock:
            # 직전 요청이 크레딧 과금이었다면 해당 키 제외
            if self.last_cost is not None and self.last_cost > 0 and self.last_key:
                self.exhausted.add(self.last_key)
                self.last_cost = None
                print(f"[keyring] 무료 소진 감지 (cost>0) → 키 제외: {self.last_key[:4]}...", flush=True)
            active = self._active()
            if not active:
                print("[keyring] 모든 키 무료 소진 — 첫 키로 계속 (크레딧 과금 감수)", flush=True)
                return self.keys[0]
            if self.i >= len(active):
                self.i = 0
            name, key = active[self.i % len(active)]
            self.i += 1
            self.last_key = name
            return key

    def on_429(self):
        """429 발생: 현재 키를 끝으로 밀고 다른 키 반환 (대기 없음).
        전환 불가(키 1개 or 전부 소진) 시 None."""
        with self._lock:
            active = self._active()
            if len(active) <= 1:
                return None
            if self.last_key and self.last_key in self.names:
                # last_key를 active 순서에서 끝으로 이동
                reordered = [x for x in active if x[0] != self.last_key] + \
                            [x for x in active if x[0] == self.last_key]
                self.names = [n for n, _ in reordered]
                self.keys = [k for _, k in reordered]
                self.i = 0
            print("[keyring] 429 → 키 전환 (다른 계정으로 재시도)", flush=True)
            return self._active()[0][1] if self._active() else None

    def set_cost(self, cost):
        """응답의 usage.cost 기록 (None이면 무시)"""
        if cost is not None:
            self.last_cost = cost

    def stats(self):
        """보안: 접두 4자 + 길이 + 상태만 (키 원문 절대 아님)"""
        out = []
        for n, k in zip(self.names, self.keys):
            status = "exhausted(크레딧)" if n in self.exhausted else "free"
            out.append(f"{n}={k[:4]}...(len={len(k)},{status})")
        return out


class Rotator:
    """요청마다 키를 번갈아 사용하는 순환자 (병렬 안전: 호출 측에서 잠금 필요 시 사용)"""

    def __init__(self):
        self.keys = get_keys()
        self.i = 0

    def next(self):
        k = self.keys[self.i % len(self.keys)]
        self.i += 1
        return k

    def stats(self):
        """보안: 접두 4자 + 길이만 반환 (키 원문 절대 아님)"""
        return [f"{k[:4]}... (len={len(k)})" for k in self.keys]


if __name__ == "__main__":
    print("키 상태:")
    for s in SmartRotator().stats():
        print(f"  {s}")