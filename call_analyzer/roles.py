"""Диаризация — присвоение ролей AGENT/PLAYER (dev spec §6.3).

Два пути:
  • 2 канала  → канал = роль (оператор на operator_channel, остальное — игрок).
  • 1 канал   → speaker-лейблы провайдера; первый говорящий в первые 30 сек =
                AGENT (исходящий звонок инициирует оператор), остальные — PLAYER.

pyannote.audio НАМЕРЕННО не подключён (тяжёлая зависимость). Оставлена
интерфейсная точка _run_pyannote(): при conf провайдера < diar_conf_min боевая
сборка должна перебить сегменты pyannote (vote); пока — только флаг low_diar_conf.
"""
from __future__ import annotations

from dataclasses import dataclass

AGENT = "AGENT"
PLAYER = "PLAYER"

# Окно, в котором ищем первого говорящего оператора (dev spec §6.3).
_AGENT_WINDOW_S = 30.0


@dataclass(frozen=True)
class DiarizationResult:
    words: list[dict]           # [{w,start,end,role,conf}]
    diarization_conf: float     # min наблюдённая уверенность
    low_diar_conf: bool         # conf < diar_conf_min → пометить аудит (dev spec §7)


def _min_conf(words: list[dict]) -> float:
    confs = [float(w.get("conf", 1.0)) for w in words if w.get("conf") is not None]
    return min(confs) if confs else 1.0


def _run_pyannote(audio_path: str | None):  # pragma: no cover - интерфейсная точка
    """Заглушка для pyannote.audio 3.1 (dev spec §6.3). Не подключаем зависимость.

    Боевая реализация: прогнать диаризацию по аудио, вернуть сегменты
    [{start,end,speaker}] и перебить ими speaker-лейблы провайдера при низкой
    уверенности. Сейчас возвращает None — пайплайн продолжает на лейблах провайдера.
    """
    return None


def assign_roles(words: list[dict], *, channels: int, diar_conf_min: float,
                 operator_channel: int = 0, audio_path: str | None = None) -> DiarizationResult:
    """Разметить роли по dev spec §6.3. Возвращает words с полем role."""
    conf = _min_conf(words)
    low = conf < diar_conf_min

    if channels == 2:
        # Канал = роль. Оператор — на operator_channel, всё прочее — игрок.
        out = [
            {**w, "role": AGENT if w.get("channel") == operator_channel else PLAYER}
            for w in words
        ]
        return DiarizationResult(words=out, diarization_conf=conf, low_diar_conf=low)

    # 1 канал: speaker-лейблы провайдера.
    if low:
        _run_pyannote(audio_path)  # интерфейсная точка; результат пока не используется

    agent_speaker = _first_speaker_in_window(words, _AGENT_WINDOW_S)
    out = []
    for w in words:
        spk = w.get("speaker")
        # Нет спикера вовсе → считаем оператором (лучше, чем потерять реплику).
        role = AGENT if (spk is None or spk == agent_speaker) else PLAYER
        out.append({**w, "role": role})
    return DiarizationResult(words=out, diarization_conf=conf, low_diar_conf=low)


def _first_speaker_in_window(words: list[dict], window_s: float):
    """Спикер первого слова в первые `window_s` секунд = оператор (dev spec §6.3)."""
    in_window = [w for w in words if float(w.get("start", 0.0)) <= window_s]
    pool = in_window or words
    if not pool:
        return None
    first = min(pool, key=lambda w: float(w.get("start", 0.0)))
    return first.get("speaker")
