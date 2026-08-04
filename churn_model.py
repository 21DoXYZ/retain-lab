"""
Point-in-time churn-модель: P(игрок уйдёт в ближайшие 30 дней).
Заменяет эвристику риска ухода (save_weight по lifecycle) калиброванной вероятностью.

Фундамент (ML_PLAN §3): срез на дату T -> фичи «как было на T» (created_at < T),
метка «не играл в (T, T+H]». Несколько месячных T -> панель. Валидация по времени.

- Население на T: играл в последние 30 дней до T И >=2 активных дней (есть что удерживать).
- Метка: НЕ сделал ни одной ставки в (T, T+H].  H=30.
- Train: ранние срезы; Test: поздний срез.
- Скоринг: срез на максимум данных -> P(churn) для текущих активных -> retention.player_churn_ml.

Запуск:  .venv/bin/python churn_model.py
"""
import os
import numpy as np
import pandas as pd
import clickhouse_connect
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
import model_registry as reg

CH = dict(host=os.environ.get('CH_HOST', '127.0.0.1'), port=int(os.environ.get('CH_PORT', '8123')),
          username=os.environ.get('CH_USER', 'default'), password=os.environ.get('CH_PASSWORD', ''),
          database=os.environ.get('CH_DB', 'retention'))

H = 30
T_TRAIN = ['2026-02-15', '2026-03-15', '2026-04-15']   # ранние срезы -> train
T_TEST = '2026-05-05'                                   # поздний срез -> test (T+30 <= данные)

NUM = ['recency_at_T', 'tenure_at_T', 'bets_to_T', 'turnover_to_T', 'active_days_to_T',
       'avg_bet', 'freespin_ratio', 'night_share', 'bets_last7', 'bets_prev7', 'bets_last30',
       'momentum_7v7', 'expected_gap', 'overdue_ratio', 'is_depositor',
       'dep_count', 'dep_sum', 'deposit_recency_at_T']
CAT = ['provider', 'country', 'affiliate_type', 'payment_method']
FEATURES = NUM + CAT

SNAP = """
WITH toDate('{T}') AS T
SELECT
  g.casino_player_id                                            AS casino_player_id,
  toUInt8(ifNull(fut.played_after, 0) = 0)                      AS churned,
  g.recency_at_T                                               AS recency_at_T,
  toInt32(if(u.reg_date IS NULL, g.tenure_proxy, dateDiff('day', toDate(u.reg_date), T))) AS tenure_at_T,
  g.bets_to_T                                                 AS bets_to_T,
  g.turnover_to_T                                             AS turnover_to_T,
  g.active_days_to_T                                          AS active_days_to_T,
  g.avg_bet                                                  AS avg_bet,
  g.freespin_ratio                                           AS freespin_ratio,
  g.night_share                                              AS night_share,
  g.bets_last7                                               AS bets_last7,
  g.bets_prev7                                               AS bets_prev7,
  g.bets_last30                                              AS bets_last30,
  round(g.bets_last7 / nullIf(g.bets_prev7, 0), 3)           AS momentum_7v7,
  g.expected_gap                                            AS expected_gap,
  round(g.recency_at_T / nullIf(g.expected_gap, 0), 3)      AS overdue_ratio,
  toUInt8(ifNull(m.dep_count, 0) > 0)                       AS is_depositor,
  ifNull(m.dep_count, 0)                                    AS dep_count,
  toFloat64(ifNull(m.dep_sum, 0))                          AS dep_sum,
  if(ifNull(m.dep_count,0) > 0, m.deposit_recency_at_T, NULL) AS deposit_recency_at_T,
  ifNull(nullIf(g.provider, ''), '(none)')                 AS provider,
  ifNull(nullIf(u.country_iso_estimated, ''), '(none)')    AS country,
  if(u.affiliate_account_type = '', '(none)', u.affiliate_account_type) AS affiliate_type,
  ifNull(nullIf(m.payment_method, ''), '(none)')           AS payment_method
FROM (
  SELECT casino_player_id,
    dateDiff('day', max(toDate(created_at)), T)                     AS recency_at_T,
    dateDiff('day', min(toDate(created_at)), T)                     AS tenure_proxy,
    count()                                                         AS bets_to_T,
    round(sum(toFloat64(bet_amount)), 2)                            AS turnover_to_T,
    uniqExact(toDate(created_at))                                   AS active_days_to_T,
    round(avg(toFloat64(bet_amount)), 2)                            AS avg_bet,
    round(countIf(transaction_type = 'freespins_bet') / count(), 3) AS freespin_ratio,
    round(countIf(toHour(toTimezone(created_at, 'Europe/Istanbul')) < 6) / count(), 3) AS night_share,
    countIf(toDate(created_at) >  T - 7)                            AS bets_last7,
    countIf(toDate(created_at) <= T - 7 AND toDate(created_at) > T - 14) AS bets_prev7,
    countIf(toDate(created_at) >  T - 30)                           AS bets_last30,
    round(dateDiff('day', min(toDate(created_at)), max(toDate(created_at))) / greatest(uniqExact(toDate(created_at)) - 1, 1), 2) AS expected_gap,
    anyHeavy(aggregator)                                            AS provider
  FROM retention.game_transactions
  WHERE transaction_type IN ('bet','freespins_bet') AND toDate(created_at) < T
    AND casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal')
  GROUP BY casino_player_id
  HAVING recency_at_T <= 30 AND active_days_to_T >= 2
) g
LEFT JOIN (
  SELECT casino_player_id, count() AS played_after
  FROM retention.game_transactions
  WHERE transaction_type IN ('bet','freespins_bet')
    AND toDate(created_at) >= T AND toDate(created_at) < T + {H}
  GROUP BY casino_player_id
) fut USING (casino_player_id)
LEFT JOIN (
  SELECT casino_player_id,
    countIf(type IN ('deposit','manual_deposit') AND status='completed') AS dep_count,
    round(sumIf(toFloat64(amount), type IN ('deposit','manual_deposit') AND status='completed'), 2) AS dep_sum,
    dateDiff('day', maxIf(toDate(created_at), type IN ('deposit','manual_deposit') AND status='completed'), T) AS deposit_recency_at_T,
    anyHeavyIf(payment_method, type IN ('deposit','manual_deposit') AND payment_method != '' AND payment_method NOT LIKE 'campaign:%') AS payment_method
  FROM retention.money_transactions
  WHERE toDate(created_at) < T
  GROUP BY casino_player_id
) m USING (casino_player_id)
INNER JOIN retention.users u USING (casino_player_id)
"""


def snapshot(client, T: str) -> pd.DataFrame:
    df = client.query_df(SNAP.format(T=T, H=H))
    df['T'] = T
    return df


def main() -> None:
    client = clickhouse_connect.get_client(**CH)
    dmax = client.query("SELECT toString(toDate(max(created_at))) FROM retention.game_transactions").result_rows[0][0]
    print(f'данные до: {dmax}  ·  горизонт H={H}')

    cat_idx = [FEATURES.index(c) for c in CAT]

    if reg.score_only():
        print('SCORE_ONLY: загружаю сохранённую модель churn (без обучения)')
        final = reg.load('churn', CatBoostClassifier)
    else:
        print('Собираю срезы (point-in-time)...')
        frames = []
        for T in T_TRAIN + [T_TEST]:
            d = snapshot(client, T)
            print(f'  T={T}: {len(d):5d} игроков · churn-rate {d.churned.mean():.3f}')
            frames.append(d)
        data = pd.concat(frames, ignore_index=True)
        for c in CAT:
            data[c] = data[c].astype(str)

        tr = data[data['T'].isin(T_TRAIN)]
        te = data[data['T'] == T_TEST]
        print(f'\n  train={len(tr)} (срезы {T_TRAIN})  ·  test={len(te)} (срез {T_TEST})')

        model = CatBoostClassifier(iterations=700, depth=6, learning_rate=0.04,
                                   loss_function='Logloss', eval_metric='AUC',
                                   random_seed=42, verbose=False)
        model.fit(Pool(tr[FEATURES], tr['churned'].values, cat_features=cat_idx),
                  eval_set=Pool(te[FEATURES], te['churned'].values, cat_features=cat_idx))

        p = model.predict_proba(Pool(te[FEATURES], cat_features=cat_idx))[:, 1]
        yte = te['churned'].values
        auc = roc_auc_score(yte, p)
        pr = average_precision_score(yte, p)
        brier = brier_score_loss(yte, p)
        print('\n=== КАЧЕСТВО (test = поздний срез, по времени) ===')
        print(f'  churn-rate (база): {yte.mean():.3f}')
        print(f'  ROC-AUC : {auc:.3f}')
        print(f'  PR-AUC  : {pr:.3f}')
        print(f'  Brier   : {brier:.3f}')
        # «остаётся» = 1 - churn: ранжируем тех, кого реально удержать
        order = np.argsort(p)  # низкий churn = скорее останется
        keep = order[:max(1, len(order) // 10)]
        print(f'  Top-10% по НИЗКОМУ риску: реально остались {(1-yte[keep]).mean()*100:.0f}% (vs база {(1-yte.mean())*100:.0f}%)')

        print('\n=== ВАЖНОСТЬ ФИЧ (топ-12) ===')
        for name, v in sorted(zip(FEATURES, model.get_feature_importance()), key=lambda t: -t[1])[:12]:
            print(f'  {name:22s} {v:5.1f}')

        # финал на всех срезах -> скоринг текущих активных (срез на dmax)
        final = CatBoostClassifier(iterations=700, depth=6, learning_rate=0.04,
                                   loss_function='Logloss', random_seed=42, verbose=False)
        final.fit(Pool(data[FEATURES], data['churned'].values, cat_features=cat_idx))
        reg.save('churn', final, features=FEATURES, cat_features=CAT,
                 metrics={'roc_auc': round(float(auc), 3), 'pr_auc': round(float(pr), 3),
                          'brier': round(float(brier), 3)},
                 extra={'horizon_days': H, 'table': 'player_churn_ml'})

    score = snapshot(client, dmax)
    for c in CAT:
        score[c] = score[c].astype(str)
    score['p_churn'] = final.predict_proba(Pool(score[FEATURES], cat_features=cat_idx))[:, 1].round(4)
    out = score[['casino_player_id', 'p_churn']].copy()
    out['casino_player_id'] = out['casino_player_id'].astype('uint32')
    out['p_churn'] = out['p_churn'].astype('float64')

    client.command('DROP TABLE IF EXISTS player_churn_ml')
    client.command('CREATE TABLE player_churn_ml (casino_player_id UInt32, p_churn Float64) '
                   'ENGINE = MergeTree ORDER BY casino_player_id')
    client.insert_df('player_churn_ml', out)
    print(f'\n✅ скоринг текущих активных записан в retention.player_churn_ml: {len(out)}'
          f'  ·  средний риск ухода {out.p_churn.mean():.3f}')


if __name__ == '__main__':
    main()
