"""Configuration for jev-mem-core (P1)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORT = 47821

ENV_PORT = "JEV_MEM_PORT"
ENV_DB = "JEV_MEM_DB"
ENV_DATA_DIR = "JEV_MEM_DATA_DIR"

# P5 (2026-09-29 승인): core 기본 DB = Hermes 실 메모리 DB.
# data_dir(jev-mem: ledger/spool/token/logs)는 유지하고 mnemosyne.db만
# Hermes가 사용하는 DB를 가리킨다 — 기존 965행 메모리 보존 + 단일 writer 완성.
# 테스트/카오스는 JEV_MEM_DB env로 오버라이드하므로 영향 없음.
def _default_mnemosyne_db() -> Path:
    # NOTE: intentionally NOT derived from JEV_MEM_DATA_DIR. data_dir holds
    # ledger/spool/token/logs; the memory DB is a separate concern (P5: the
    # default is the Hermes live DB regardless of where the data dir is).
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes" / "mnemosyne" / "data" / "mnemosyne.db"


@dataclass
class Config:
    # server
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    max_body_bytes: int = 1_048_576  # 1 MiB (B §5.1)
    # paths
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "jev-mem"
    )
    mnemosyne_db: Path | None = None  # None -> Hermes 실 메모리 DB (P5)
    # writer
    writer_max_queue_depth: int = 500
    writer_slow_job_warn_ms: int = 500  # v1.1 D14: remember() 임베딩 포함 ~0.1s 대비
    # readers
    readers_workers: int = 2
    embedding_workers: int = 2  # D3a: 스레드풀 1개 통일 (onnxruntime GIL 해제)
    # JEV
    jev_max_concurrency: int = 4
    jev_request_timeout_ms: int = 15000  # write_gate 타임아웃 유지 (실측 0.24~23s)
    jev_retries: int = 1
    # prefetch (D7a)
    prefetch_default_timeout_ms: int = 1500  # 기본 1.5s
    prefetch_max_timeout_ms: int = 2000  # 상한 2.0s
    # session lock
    session_lock_idle_s: int = 600
    # P2: spool (D6 — adapter writes, core replays)
    spool_max_bytes: int = 50 * 1024 * 1024  # 50 MiB per agent (B §9.1)
    spool_replay_interval_s: int = 600  # scan every 10 min
    spool_skip_fresh_s: int = 10  # skip files modified <10s ago (B §9.3.5)
    # P2: pending_gate (D7 — B §8.2)
    pending_gate_max_age_h: int = 24
    pending_gate_retry_interval_s: int = 60
    pending_gate_batch: int = 20
    # P2: DB ops (B §13)
    checkpoint_idle_interval_s: int = 300  # wal_checkpoint(PASSIVE)
    backup_interval_h: int = 24
    backup_keep: int = 7
    backup_lock_retries: int = 3  # 2s apart (D11d: spool/backup only)
    # P3: 자동 재판정 (fail-open quarantine → rejudge worker)
    #   - 회복 감지: 실제 사용자 호출 success streak (주기 프로브 금지)
    #   - 실행 주체: core 내부 worker (외부 AI 3종 만장일치, D1-D8)
    auto_rejudge: bool = True              # JEV_AUTO_REJUDGE=0 → 수동 도구만
    rejudge_batch: int = 5                 # 1회 루프당 최대 재판정 수
    rejudge_interval_s: int = 60           # worker 체크 주기 (requeue와 병렬)
    rejudge_concurrency: int = 1           # JEV 동시 호출 상한 (foreground보다 낮게)
    rejudge_streak: int = 3                # 회복 판정: 연속 성공 횟수
    rejudge_cooldown_min: int = 30         # 회복 후 재판정 시작까지 대기 (히스테리시스)
    rejudge_lease_s: int = 120             # 행 claim lease (만료 → pending 복구)
    rejudge_billing_halt: bool = True      # 재판정 중 billing/auth 1회 실패 → 즉시 중단
    rejudge_transient_halt: int = 3        # 일시 오류 연속 N회 → 중단
    # D-5 (2026-09-30, review F10): idle shutdown — graceful exit when all of:
    # no non-probe activity for N minutes, writer queue empty, no pending_gate
    # or spool backlog. 0 disables. Default 60 per review recommendation.
    idle_shutdown_min: int = 60
    # D-3 (2026-09-30, review F13): redaction on the STORE path (what reaches
    # mnemosyne.db), not just ledger/spool. High-precision patterns only —
    # entropy-based detection stays off to avoid false positives on prose.
    store_redact: bool = True
    # P2: core.log rotation (B §14)
    log_dir: Path | None = None  # None -> data_dir/logs

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        cfg = cls()
        # env overrides first (lowest priority: file < env)
        if os.environ.get(ENV_PORT):
            cfg.port = int(os.environ[ENV_PORT])
        if os.environ.get(ENV_DB):
            cfg.mnemosyne_db = Path(_expand(os.environ[ENV_DB]))
        if os.environ.get(ENV_DATA_DIR):
            cfg.data_dir = Path(_expand(os.environ[ENV_DATA_DIR]))

        # config.toml (file overrides env? no: env wins over file is safer for tests)
        if path and path.exists():
            try:
                with open(path, "rb") as f:
                    data = tomllib.load(f)
            except tomllib.TOMLDecodeError as e:
                raise SystemExit(f"config.toml parse error: {e}") from e
            srv = data.get("server", {})
            pth = data.get("paths", {})
            w = data.get("writer", {})
            r = data.get("readers", {})
            emb = data.get("embedding", {})
            jv = data.get("jev", {})
            pf = data.get("prefetch", {})
            sp = data.get("spool", {})
            pg = data.get("pending_gate", {})
            ops = data.get("ops", {})
            if "host" in srv:
                cfg.host = srv["host"]
            if "port" in srv:
                cfg.port = int(srv["port"])
            if "max_body_bytes" in srv:
                cfg.max_body_bytes = int(srv["max_body_bytes"])
            if "data_dir" in pth:
                cfg.data_dir = Path(_expand(str(pth["data_dir"])))
            if "mnemosyne_db" in pth:
                cfg.mnemosyne_db = Path(_expand(str(pth["mnemosyne_db"])))
            if "max_queue_depth" in w:
                cfg.writer_max_queue_depth = int(w["max_queue_depth"])
            if "slow_job_warn_ms" in w:
                cfg.writer_slow_job_warn_ms = int(w["slow_job_warn_ms"])
            if "workers" in r:
                cfg.readers_workers = int(r["workers"])
            if "workers" in emb:
                cfg.embedding_workers = int(emb["workers"])
            if "max_concurrency" in jv:
                cfg.jev_max_concurrency = int(jv["max_concurrency"])
            if "request_timeout_ms" in jv:
                cfg.jev_request_timeout_ms = int(jv["request_timeout_ms"])
            if "retries" in jv:
                cfg.jev_retries = int(jv["retries"])
            if "default_timeout_ms" in pf:
                cfg.prefetch_default_timeout_ms = int(pf["default_timeout_ms"])
            if "max_timeout_ms" in pf:
                cfg.prefetch_max_timeout_ms = int(pf["max_timeout_ms"])
            if "max_bytes" in sp:
                cfg.spool_max_bytes = int(sp["max_bytes"])
            if "replay_interval_s" in sp:
                cfg.spool_replay_interval_s = int(sp["replay_interval_s"])
            if "skip_fresh_s" in sp:
                cfg.spool_skip_fresh_s = int(sp["skip_fresh_s"])
            if "max_age_h" in pg:
                cfg.pending_gate_max_age_h = int(pg["max_age_h"])
            if "retry_interval_s" in pg:
                cfg.pending_gate_retry_interval_s = int(pg["retry_interval_s"])
            if "batch" in pg:
                cfg.pending_gate_batch = int(pg["batch"])
            if "checkpoint_idle_interval_s" in ops:
                cfg.checkpoint_idle_interval_s = int(ops["checkpoint_idle_interval_s"])
            if "backup_interval_h" in ops:
                cfg.backup_interval_h = int(ops["backup_interval_h"])
            if "backup_keep" in ops:
                cfg.backup_keep = int(ops["backup_keep"])
            if "backup_lock_retries" in ops:
                cfg.backup_lock_retries = int(ops["backup_lock_retries"])
            if "idle_shutdown_min" in ops:
                cfg.idle_shutdown_min = int(ops["idle_shutdown_min"])
            if "store_redact" in ops:
                cfg.store_redact = bool(ops["store_redact"])
            if "auto_rejudge" in ops:
                cfg.auto_rejudge = bool(ops["auto_rejudge"])
            if "rejudge_batch" in ops:
                cfg.rejudge_batch = int(ops["rejudge_batch"])
            if "rejudge_interval_s" in ops:
                cfg.rejudge_interval_s = int(ops["rejudge_interval_s"])
            if "rejudge_concurrency" in ops:
                cfg.rejudge_concurrency = int(ops["rejudge_concurrency"])
            if "rejudge_streak" in ops:
                cfg.rejudge_streak = int(ops["rejudge_streak"])
            if "rejudge_cooldown_min" in ops:
                cfg.rejudge_cooldown_min = int(ops["rejudge_cooldown_min"])
            if "rejudge_lease_s" in ops:
                cfg.rejudge_lease_s = int(ops["rejudge_lease_s"])
            if "rejudge_billing_halt" in ops:
                cfg.rejudge_billing_halt = bool(ops["rejudge_billing_halt"])
            if "rejudge_transient_halt" in ops:
                cfg.rejudge_transient_halt = int(ops["rejudge_transient_halt"])
            if "log_dir" in pth:
                cfg.log_dir = Path(_expand(str(pth["log_dir"])))

        # env re-override (tests use env to point at scratch DBs)
        if os.environ.get(ENV_PORT):
            cfg.port = int(os.environ[ENV_PORT])
        if os.environ.get(ENV_DB):
            cfg.mnemosyne_db = Path(_expand(os.environ[ENV_DB]))
        if os.environ.get(ENV_DATA_DIR):
            cfg.data_dir = Path(_expand(os.environ[ENV_DATA_DIR]))
        # P3 rejudge env re-override (config.toml보다 env가 최종 승자)
        if os.environ.get("JEV_AUTO_REJUDGE") is not None:
            cfg.auto_rejudge = os.environ["JEV_AUTO_REJUDGE"].strip().lower() not in ("0", "false", "no")
        if os.environ.get("JEV_REJUDGE_BATCH"):
            cfg.rejudge_batch = int(os.environ["JEV_REJUDGE_BATCH"])
        if os.environ.get("JEV_REJUDGE_STREAK"):
            cfg.rejudge_streak = int(os.environ["JEV_REJUDGE_STREAK"])
        if os.environ.get("JEV_REJUDGE_COOLDOWN_MIN"):
            cfg.rejudge_cooldown_min = int(os.environ["JEV_REJUDGE_COOLDOWN_MIN"])
        if os.environ.get("JEV_REJUDGE_LEASE_S"):
            cfg.rejudge_lease_s = int(os.environ["JEV_REJUDGE_LEASE_S"])
        if os.environ.get("JEV_REJUDGE_TRANSIENT_HALT"):
            cfg.rejudge_transient_halt = int(os.environ["JEV_REJUDGE_TRANSIENT_HALT"])
        if os.environ.get("JEV_REJUDGE_BILLING_HALT") is not None:
            cfg.rejudge_billing_halt = os.environ["JEV_REJUDGE_BILLING_HALT"].strip().lower() not in ("0", "false", "no")
        if os.environ.get("JEV_REJUDGE_CONCURRENCY"):
            cfg.rejudge_concurrency = int(os.environ["JEV_REJUDGE_CONCURRENCY"])

        # default db path (P5: Hermes 실 메모리 DB 유지)
        if cfg.mnemosyne_db is None:
            cfg.mnemosyne_db = _default_mnemosyne_db()
        return cfg

    @property
    def state_db(self) -> Path:
        return self.data_dir / "core_state.db"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "token"

    @property
    def core_json_path(self) -> Path:
        return self.data_dir / "core.json"

    @property
    def prefetch_timeout_clamp(self) -> tuple[int, int]:
        return (self.prefetch_default_timeout_ms, self.prefetch_max_timeout_ms)


def _expand(s: str) -> str:
    return os.path.expandvars(s)