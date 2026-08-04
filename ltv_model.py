"""
CatBoost LTV-регрессор: прогноз накопленного депозита на D90 по поведению ПЕРВОЙ НЕДЕЛИ.
Заменяет грубый v0-лукап (ltv_tier_model) на персональный калиброванный прогноз.

- Обучение: депозиторы (account_type='normal'), у кого с FTD прошло >=90 дней (target наблюдаем).
- Валидация: по времени (ранние FTD -> train, поздние -> test), чтобы не было утечки.
- Таргет в log1p (распределение тяжёлохвостое — киты).
- Скоринг: ВСЕ депозиторы -> таблица retention.player_ltv_ml.

Запуск:  .venv/bin/python ltv_model.py
"""
import os
import numpy as np
import pandas as pd
import clickhouse_connect
from catboost import CatBoostRegressor, Pool
from sklearn.metrics import mean_absolute_error, r2_score
from scipy.stats import spearmanr
import model_registry as reg

CH = dict(host=os.environ.get('CH_HOST', '127.0.0.1'), port=int(os.environ.get('CH_PORT', '8123')),
          username=os.environ.get('CH_USER', 'default'), password=os.environ.get('CH_PASSWORD', ''),
          database=os.environ.get('CH_DB', 'retention'))

NUM = ['ftd_amount', 'act_lag_days', 'dep_d1', 'dep_d7', 'ndep_d7',
       'bets_d7', 'turnover_d7', 'avg_bet_d7', 'distinct_games_d7', 'active_days_d7',
       'freespin_d7', 'night_d7']
CAT = ['provider_d7', 'payment_method', 'affiliate_type', 'country']
FEATURES = NUM + CAT

FEATURE_SQL = """
WITH (SELECT toDate(max(created_at)) FROM money_transactions) AS dmax
SELECT
  u.casino_player_id                                                        AS casino_player_id,
  toUInt32(dateDiff('day', toDate(u.ftd_date), dmax))                       AS mat,
  toFloat64(ifNull(u.ftd_amount, 0))                                        AS ftd_amount,
  toFloat64(if(u.reg_date IS NULL, 0, greatest(dateDiff('day', toDate(u.reg_date), toDate(u.ftd_date)), 0))) AS act_lag_days,
  -- депозиты по окнам от FTD
  toFloat64(d.dep_d1)                                                       AS dep_d1,
  toFloat64(d.dep_d7)                                                       AS dep_d7,
  toFloat64(d.ndep_d7)                                                      AS ndep_d7,
  toFloat64(d.target_d90)                                                   AS target_d90,
  -- игра первой недели
  toFloat64(ifNull(g.bets_d7, 0))                                          AS bets_d7,
  toFloat64(ifNull(g.turnover_d7, 0))                                      AS turnover_d7,
  toFloat64(ifNull(g.avg_bet_d7, 0))                                       AS avg_bet_d7,
  toFloat64(ifNull(g.distinct_games_d7, 0))                               AS distinct_games_d7,
  toFloat64(ifNull(g.active_days_d7, 0))                                  AS active_days_d7,
  toFloat64(ifNull(g.freespin_d7, 0))                                     AS freespin_d7,
  toFloat64(ifNull(g.night_d7, 0))                                        AS night_d7,
  ifNull(nullIf(g.provider_d7, ''), '(none)')                             AS provider_d7,
  if(u.affiliate_account_type = '', '(none)', u.affiliate_account_type)   AS affiliate_type,
  ifNull(nullIf(pm.payment_method, ''), '(none)')                         AS payment_method,
  ifNull(nullIf(u.country_iso_estimated, ''), '(none)')                   AS country,
  toString(toDate(u.ftd_date))                                            AS ftd_date
FROM users u
INNER JOIN (
  SELECT casino_player_id,
    sumIf(toFloat64(amount), off >= 0 AND off <= 1)  AS dep_d1,
    sumIf(toFloat64(amount), off >= 0 AND off <= 7)  AS dep_d7,
    countIf(off >= 0 AND off <= 7)                   AS ndep_d7,
    sumIf(toFloat64(amount), off >= 0 AND off <= 90) AS target_d90
  FROM (
    SELECT m.casino_player_id AS casino_player_id, m.amount AS amount,
           dateDiff('day', toDate(u2.ftd_date), toDate(m.created_at)) AS off
    FROM money_transactions m
    INNER JOIN users u2 USING (casino_player_id)
    WHERE u2.account_type = 'normal' AND u2.ftd_date IS NOT NULL
      AND m.type IN ('deposit', 'manual_deposit') AND m.status = 'completed'
  ) GROUP BY casino_player_id
) d USING (casino_player_id)
LEFT JOIN (
  SELECT casino_player_id,
    countIf(rb)                                              AS bets_d7,
    sumIf(toFloat64(bet_amount), rb)                         AS turnover_d7,
    round(avgIf(toFloat64(bet_amount), rb), 2)               AS avg_bet_d7,
    uniqExactIf(game_uuid, rb)                               AS distinct_games_d7,
    uniqExactIf(toDate(created_at), rb)                      AS active_days_d7,
    countIf(rb AND transaction_type = 'freespins_bet')      AS freespin_d7,
    countIf(rb AND toHour(toTimezone(created_at, 'Europe/Istanbul')) < 6) AS night_d7,
    anyHeavyIf(aggregator, rb)                               AS provider_d7
  FROM (
    SELECT gt.casino_player_id AS casino_player_id, gt.bet_amount, gt.game_uuid, gt.created_at,
           gt.transaction_type AS transaction_type, gt.aggregator AS aggregator,
           (gt.transaction_type IN ('bet','freespins_bet')
            AND dateDiff('day', toDate(u3.ftd_date), toDate(gt.created_at)) BETWEEN 0 AND 7) AS rb
    FROM game_transactions gt
    INNER JOIN users u3 USING (casino_player_id)
    WHERE u3.account_type = 'normal' AND u3.ftd_date IS NOT NULL
  ) GROUP BY casino_player_id
) g USING (casino_player_id)
LEFT JOIN (
  SELECT casino_player_id,
    anyHeavyIf(payment_method, type IN ('deposit','manual_deposit') AND payment_method != '' AND payment_method NOT LIKE 'campaign:%') AS payment_method
  FROM money_transactions GROUP BY casino_player_id
) pm USING (casino_player_id)
WHERE u.account_type = 'normal' AND u.ftd_date IS NOT NULL
"""


def main() -> None:
    client = clickhouse_connect.get_client(**CH)
    print('Загружаю фичи из ClickHouse...')
    df = client.query_df(FEATURE_SQL)
    print(f'  всего депозиторов: {len(df)}')

    for c in CAT:
        df[c] = df[c].astype(str)

    cat_idx = [FEATURES.index(c) for c in CAT]

    if reg.score_only():
        print('SCORE_ONLY: загружаю сохранённую модель ltv (без обучения)')
        final = reg.load('ltv', CatBoostRegressor)
    else:
        mature = df[df['mat'] >= 90].copy()
        print(f'  дозревших (mat>=90, для обучения): {len(mature)}')

        # лог-таргет (тяжёлый хвост из-за китов)
        mature = mature.sort_values('ftd_date').reset_index(drop=True)
        y = np.log1p(mature['target_d90'].clip(lower=0).values)
        X = mature[FEATURES]

        # временная валидация: ранние 80% FTD -> train, поздние 20% -> test
        split = int(len(mature) * 0.8)
        Xtr, Xte = X.iloc[:split], X.iloc[split:]
        ytr, yte = y[:split], y[split:]

        print(f'  train={len(Xtr)}  test={len(Xte)} (по времени)')
        model = CatBoostRegressor(iterations=600, depth=6, learning_rate=0.05,
                                  loss_function='RMSE', random_seed=42, verbose=False)
        model.fit(Pool(Xtr, ytr, cat_features=cat_idx), eval_set=Pool(Xte, yte, cat_features=cat_idx))

        # оценка в РЕАЛЬНЫХ рублях (обратный log)
        pred_te = np.expm1(model.predict(Pool(Xte, cat_features=cat_idx)))
        true_te = np.expm1(yte)
        mae = mean_absolute_error(true_te, pred_te)
        r2 = r2_score(true_te, pred_te)
        rho = spearmanr(true_te, pred_te).correlation
        print('\n=== КАЧЕСТВО (test, по времени) ===')
        print(f'  MAE        : {mae:,.0f} TRY  (средняя в тесте: {true_te.mean():,.0f})')
        print(f'  R^2        : {r2:.3f}')
        print(f'  Spearman   : {rho:.3f}  (ранжирование — насколько верно сортирует по ценности)')

        # lift: топ-10% по предсказанию — какую долю реального LTV ловим
        order = np.argsort(-pred_te)
        top10 = order[:max(1, len(order) // 10)]
        lift = true_te[top10].sum() / true_te.sum()
        print(f'  Top-10% pred ловят {lift*100:.0f}% всего реального D90-депозита (концентрация китов)')

        print('\n=== ВАЖНОСТЬ ФИЧ (топ-10) ===')
        imp = sorted(zip(FEATURES, model.get_feature_importance()), key=lambda t: -t[1])
        for name, v in imp[:10]:
            print(f'  {name:20s} {v:5.1f}')

        # финальная модель на ВСЕЙ дозревшей когорте -> скоринг всех депозиторов
        final = CatBoostRegressor(iterations=600, depth=6, learning_rate=0.05,
                                  loss_function='RMSE', random_seed=42, verbose=False)
        final.fit(Pool(X, y, cat_features=cat_idx))
        reg.save('ltv', final, features=FEATURES, cat_features=CAT,
                 metrics={'mae': round(float(mae), 1), 'r2': round(float(r2), 3),
                          'spearman': round(float(rho), 3), 'top10_lift': round(float(lift), 3)},
                 extra={'target': 'log1p(deposit_d90)', 'table': 'player_ltv_ml'})
    df['pred_ltv_d90_ml'] = np.expm1(final.predict(Pool(df[FEATURES], cat_features=cat_idx))).clip(min=0).round(0)

    out = df[['casino_player_id', 'pred_ltv_d90_ml']].copy()
    out['casino_player_id'] = out['casino_player_id'].astype('uint32')
    out['pred_ltv_d90_ml'] = out['pred_ltv_d90_ml'].astype('float64')

    client.command('DROP TABLE IF EXISTS player_ltv_ml')
    client.command('CREATE TABLE player_ltv_ml (casino_player_id UInt32, pred_ltv_d90_ml Float64) '
                   'ENGINE = MergeTree ORDER BY casino_player_id')
    client.insert_df('player_ltv_ml', out)
    print(f'\n✅ записано прогнозов в retention.player_ltv_ml: {len(out)}')
    print('   топ-5 по ML-прогнозу:')
    top = out.sort_values('pred_ltv_d90_ml', ascending=False).head(5)
    for _, r in top.iterrows():
        print(f'     player {int(r.casino_player_id):>6}  ->  {r.pred_ltv_d90_ml:>12,.0f} TRY')


if __name__ == '__main__':
    main()
