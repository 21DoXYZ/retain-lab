"""
Квантильная LTV-модель: вместо одного числа — диапазон P10 / P50 / P90 по депозиту D90.
Честно показывает разброс (киты): «медиана X, но с шансом верх до Y».

Три CatBoost-регрессора (Quantile alpha=0.1/0.5/0.9) на тех же фичах 1-й недели, что ltv_model.
Пишет retention.player_ltv_quantiles(casino_player_id, ltv_p10, ltv_p50, ltv_p90).

Запуск:  .venv/bin/python ltv_quantiles.py
"""
import os
import numpy as np
import clickhouse_connect
from catboost import CatBoostRegressor, Pool
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
  u.casino_player_id AS casino_player_id,
  toUInt32(dateDiff('day', toDate(u.ftd_date), dmax)) AS mat,
  toFloat64(ifNull(u.ftd_amount, 0)) AS ftd_amount,
  toFloat64(if(u.reg_date IS NULL, 0, greatest(dateDiff('day', toDate(u.reg_date), toDate(u.ftd_date)), 0))) AS act_lag_days,
  toFloat64(d.dep_d1) AS dep_d1, toFloat64(d.dep_d7) AS dep_d7, toFloat64(d.ndep_d7) AS ndep_d7,
  toFloat64(d.target_d90) AS target_d90,
  toFloat64(ifNull(g.bets_d7, 0)) AS bets_d7, toFloat64(ifNull(g.turnover_d7, 0)) AS turnover_d7,
  toFloat64(ifNull(g.avg_bet_d7, 0)) AS avg_bet_d7, toFloat64(ifNull(g.distinct_games_d7, 0)) AS distinct_games_d7,
  toFloat64(ifNull(g.active_days_d7, 0)) AS active_days_d7, toFloat64(ifNull(g.freespin_d7, 0)) AS freespin_d7,
  toFloat64(ifNull(g.night_d7, 0)) AS night_d7,
  ifNull(nullIf(g.provider_d7, ''), '(none)') AS provider_d7,
  if(u.affiliate_account_type = '', '(none)', u.affiliate_account_type) AS affiliate_type,
  ifNull(nullIf(pm.payment_method, ''), '(none)') AS payment_method,
  ifNull(nullIf(u.country_iso_estimated, ''), '(none)') AS country
FROM users u
INNER JOIN (
  SELECT casino_player_id,
    sumIf(toFloat64(amount), off>=0 AND off<=1) AS dep_d1,
    sumIf(toFloat64(amount), off>=0 AND off<=7) AS dep_d7,
    countIf(off>=0 AND off<=7) AS ndep_d7,
    sumIf(toFloat64(amount), off>=0 AND off<=90) AS target_d90
  FROM (
    SELECT m.casino_player_id AS casino_player_id, m.amount AS amount,
           dateDiff('day', toDate(u2.ftd_date), toDate(m.created_at)) AS off
    FROM money_transactions m INNER JOIN users u2 USING (casino_player_id)
    WHERE u2.account_type='normal' AND u2.ftd_date IS NOT NULL
      AND m.type IN ('deposit','manual_deposit') AND m.status='completed'
  ) GROUP BY casino_player_id
) d USING (casino_player_id)
LEFT JOIN (
  SELECT casino_player_id,
    countIf(rb) AS bets_d7, sumIf(toFloat64(bet_amount), rb) AS turnover_d7,
    round(avgIf(toFloat64(bet_amount), rb), 2) AS avg_bet_d7, uniqExactIf(game_uuid, rb) AS distinct_games_d7,
    uniqExactIf(toDate(created_at), rb) AS active_days_d7,
    countIf(rb AND transaction_type='freespins_bet') AS freespin_d7,
    countIf(rb AND toHour(toTimezone(created_at,'Europe/Istanbul'))<6) AS night_d7,
    anyHeavyIf(aggregator, rb) AS provider_d7
  FROM (
    SELECT gt.casino_player_id AS casino_player_id, gt.bet_amount, gt.game_uuid, gt.created_at,
           gt.transaction_type AS transaction_type, gt.aggregator AS aggregator,
           (gt.transaction_type IN ('bet','freespins_bet')
            AND dateDiff('day', toDate(u3.ftd_date), toDate(gt.created_at)) BETWEEN 0 AND 7) AS rb
    FROM game_transactions gt INNER JOIN users u3 USING (casino_player_id)
    WHERE u3.account_type='normal' AND u3.ftd_date IS NOT NULL
  ) GROUP BY casino_player_id
) g USING (casino_player_id)
LEFT JOIN (
  SELECT casino_player_id,
    anyHeavyIf(payment_method, type IN ('deposit','manual_deposit') AND payment_method!='' AND payment_method NOT LIKE 'campaign:%') AS payment_method
  FROM money_transactions GROUP BY casino_player_id
) pm USING (casino_player_id)
WHERE u.account_type='normal' AND u.ftd_date IS NOT NULL
"""


def main():
    client = clickhouse_connect.get_client(**CH)
    df = client.query_df(FEATURE_SQL)
    for c in CAT:
        df[c] = df[c].astype(str)
    cat_idx = [FEATURES.index(c) for c in CAT]
    QUANTILES = [('p10', 0.1), ('p50', 0.5), ('p90', 0.9)]
    preds = {}
    if reg.score_only():
        print('SCORE_ONLY: загружаю сохранённые квантильные модели (без обучения)')
        for tag, _ in QUANTILES:
            m = reg.load('ltv_quantiles', CatBoostRegressor, artifact=tag)
            preds[tag] = np.expm1(m.predict(Pool(df[FEATURES], cat_features=cat_idx))).clip(min=0)
    else:
        mature = df[df['mat'] >= 90].copy()
        y = np.log1p(mature['target_d90'].clip(lower=0).values)
        X = mature[FEATURES]
        print(f'обучаю квантильные модели на {len(mature)} дозревших...')
        for tag, alpha in QUANTILES:
            m = CatBoostRegressor(iterations=500, depth=6, learning_rate=0.05,
                                  loss_function=f'Quantile:alpha={alpha}', random_seed=42, verbose=False)
            m.fit(Pool(X, y, cat_features=cat_idx))
            preds[tag] = np.expm1(m.predict(Pool(df[FEATURES], cat_features=cat_idx))).clip(min=0)
            reg.save('ltv_quantiles', m, artifact=tag, features=FEATURES, cat_features=CAT,
                     extra={'target': 'log1p(deposit_d90)', 'table': 'player_ltv_quantiles'})
            print(f'  {tag} (alpha={alpha}) готова')
    # монотонность: p10<=p50<=p90
    p10 = np.minimum(preds['p10'], preds['p50'])
    p90 = np.maximum(preds['p90'], preds['p50'])
    out = df[['casino_player_id']].copy()
    out['ltv_p10'] = p10.round(0).astype('float64')
    out['ltv_p50'] = preds['p50'].round(0).astype('float64')
    out['ltv_p90'] = p90.round(0).astype('float64')
    out['casino_player_id'] = out['casino_player_id'].astype('uint32')
    client.command('DROP TABLE IF EXISTS player_ltv_quantiles')
    client.command('CREATE TABLE player_ltv_quantiles (casino_player_id UInt32, ltv_p10 Float64, ltv_p50 Float64, ltv_p90 Float64) '
                   'ENGINE = MergeTree ORDER BY casino_player_id')
    client.insert_df('player_ltv_quantiles', out)
    print(f'✅ квантили LTV записаны: {len(out)}  ·  медиана P50={out.ltv_p50.median():.0f}  P90={out.ltv_p90.median():.0f}')


if __name__ == '__main__':
    main()
