"""
Реестр моделей: сохранение/загрузка обученных CatBoost-моделей + метаданные.

Зачем: модели больше не «живут» только строками предсказаний в ClickHouse — сам обученный
артефакт сохраняется в файл (`models/<name>/<artifact>.cbm`). Это даёт:
  • перенос на VPS без переобучения (скоринг по сохранённой модели);
  • воспроизводимость и версионирование (meta.json: когда обучена, метрики, фичи);
  • быстрый ре-скоринг (SCORE_ONLY=1 — пропустить обучение, загрузить .cbm, предиктить).

Использование в *_model.py:
    import model_registry as reg
    if reg.score_only():
        final = reg.load('ltv', CatBoostRegressor)
    else:
        ... обучение ...
        reg.save('ltv', final, features=FEATURES, cat_features=CAT, metrics={...})

Конфиг каталога: env MODELS_DIR (по умолчанию ./models рядом со скриптами).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

MODELS_DIR = Path(os.environ.get('MODELS_DIR', Path(__file__).resolve().parent / 'models'))


def score_only() -> bool:
    """SCORE_ONLY=1 → не обучать, загрузить сохранённую модель и только заскорить."""
    return os.environ.get('SCORE_ONLY', '').strip().lower() in ('1', 'true', 'yes', 'on')


def _dir(name: str) -> Path:
    d = MODELS_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(name: str, model, *, artifact: str = 'model',
         features=None, cat_features=None, metrics=None, extra=None) -> Path:
    """Сохранить модель в models/<name>/<artifact>.cbm и обновить meta.json.

    Для мультимодельных (квантили) вызывать несколько раз с разным `artifact`.
    """
    d = _dir(name)
    model.save_model(str(d / f'{artifact}.cbm'))

    meta_path = d / 'meta.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
    meta['name'] = name
    meta['trained_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    meta['artifacts'] = sorted(set(meta.get('artifacts', [])) | {f'{artifact}.cbm'})
    if features is not None:
        meta['features'] = list(features)
    if cat_features is not None:
        meta['cat_features'] = list(cat_features)
    if metrics is not None:
        meta.setdefault('metrics', {}).update(metrics)
    if extra:
        meta.update(extra)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    return d


def load(name: str, model_factory, *, artifact: str = 'model'):
    """Загрузить сохранённую модель. model_factory — класс (CatBoostRegressor/Classifier)."""
    path = MODELS_DIR / name / f'{artifact}.cbm'
    if not path.exists():
        raise FileNotFoundError(
            f'Нет сохранённой модели {path}. Сначала обучи без SCORE_ONLY: python {name}_model.py')
    m = model_factory()
    m.load_model(str(path))
    return m


def meta(name: str) -> dict:
    """Прочитать meta.json модели (или {} если нет)."""
    p = MODELS_DIR / name / 'meta.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
