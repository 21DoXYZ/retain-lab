"""Конфиг сервиса (dev spec §12).

Дефолты — в коде; боевые значения приходят из analyzer.settings.config (jsonb) +
пары колонок (random_sample_per_day, min_review_time_s, verdict_unlocked).
Hot-reload = перечитывать при КАЖДОМ задании (дёшево, одна строка): load_config()
вызывается на входе пайплайна/дискавери, кэш не держим.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from call_analyzer.prompts import RUBRIC_V1_BLOCK
from call_analyzer.scoring import DEFAULT_WEIGHTS


class ConfigError(RuntimeError):
    """Обязательный секрет/параметр не задан (turnkey: конструктор ок, вызов падает)."""


@dataclass(frozen=True)
class Config:
    """Слепок конфигурации на одно задание. frozen: правки — через replace()."""
    # ── рубрика/подсчёт (dev spec §9, §10.3, §12) ────────────────────────────────
    prompt_version: str = "v1"
    rubric_version: str = "v1"
    rubric_block: str = RUBRIC_V1_BLOCK
    weights: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    pass_threshold: int = 70
    review_low: int = 50
    # ── аудио/диаризация ─────────────────────────────────────────────────────────
    snr_min: float = 8.0
    diar_conf_min: float = 0.6
    operator_channel: int = 0
    # ── модели/провайдеры ────────────────────────────────────────────────────────
    primary_model: str = "google/gemini-3-flash"
    fallback_model: str = "qwen/qwen3-235b-a22b"
    asr_provider: str = "gladia"
    output_lang: str = "ru"
    # ── флаги подлинности / очередь (интерфейс §11.4, §7) ────────────────────────
    too_short_s: int = 10
    repeated_pattern_min: int = 5
    random_sample_per_day: int = 2
    min_review_time_s: int = 20
    # ── состояние вердикта (интерфейс §7) ────────────────────────────────────────
    verdict_unlocked: bool = False
    casino_id: str = "default"

    # ключи settings.config (jsonb), которые накладываются поверх дефолтов
    _CONFIG_KEYS = (
        "prompt_version", "rubric_version", "rubric_block", "weights",
        "pass_threshold", "review_low", "snr_min", "diar_conf_min",
        "operator_channel", "primary_model", "fallback_model", "asr_provider",
        "output_lang", "too_short_s", "repeated_pattern_min",
    )

    def merged(self, cfg_json: dict | None, *, random_sample_per_day: int | None = None,
               min_review_time_s: int | None = None, verdict_unlocked: bool | None = None,
               casino_id: str | None = None) -> "Config":
        """Наложить значения из settings на дефолты (только известные ключи)."""
        overrides: dict = {}
        for k, v in (cfg_json or {}).items():
            if k in self._CONFIG_KEYS and v is not None:
                overrides[k] = v
        if random_sample_per_day is not None:
            overrides["random_sample_per_day"] = random_sample_per_day
        if min_review_time_s is not None:
            overrides["min_review_time_s"] = min_review_time_s
        if verdict_unlocked is not None:
            overrides["verdict_unlocked"] = verdict_unlocked
        if casino_id is not None:
            overrides["casino_id"] = casino_id
        return replace(self, **overrides)


def load_config(conn_factory=None, casino_id: str = "default") -> Config:
    """Прочитать конфиг казино из analyzer.settings (dev spec §12).

    Нет БД/строки — возвращаем дефолты (turnkey: сервис поднимается без настроек).
    conn_factory инжектируется в тестах; None → ленивое подключение из db.
    """
    base = Config()
    try:
        from call_analyzer import db  # noqa: PLC0415 — ленивый импорт, разрыв цикла
        row = db.get_settings(casino_id, conn_factory=conn_factory) if conn_factory \
            else db.get_settings(casino_id)
    except Exception:  # noqa: BLE001 — БД недоступна → дефолты (не падаем)
        return base
    if not row:
        return base
    return base.merged(
        row.get("config"),
        random_sample_per_day=row.get("random_sample_per_day"),
        min_review_time_s=row.get("min_review_time_s"),
        verdict_unlocked=row.get("verdict_unlocked"),
        casino_id=casino_id,
    )
