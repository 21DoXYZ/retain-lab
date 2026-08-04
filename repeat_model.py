"""
CatBoost-классификатор: P(2-й депозит в 30 дней) по поведению ПЕРВОГО ДНЯ.
Заменяет эмпирический repeat_deposit_model (лукап по тиру FTD).

Защита от утечки: фичи берём ТОЛЬКО из FTD-дня (offset=0) + сам FTD.
Депозит-агрегаты за окно НЕ используем (они бы включили искомый 2-й депозит).

- Население: депозиторы (normal), у кого с FTD прошло >=30 дней (target наблюдаем).
- Таргет: сделал >=2 завершённых депозита в пределах 30 дней от FTD.
- Валидация: по времени (ранние FTD -> train, поздние -> test).
- Скоринг: все депозиторы -> retention.player_repeat_ml (P 2-го депозита).

Запуск:  .venv/bin/python repeat_model.py
"""
import os
import numpy as np
import clickhouse_connect
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
import model_registry as reg

CH = dict(host=os.environ.get('CH_HOST', '127.0.0.1'), port=int(os.environ.get('CH_PORT', '8123')),
          username=os.environ.get('CH_USER', 'default'), password=os.environ.get('CH_PASSWORD', ''),
          database=os.environ.get('CH_DB', 'retention'))

NUM = ['ftd_amount', 'act_lag_days', 'bets_d0', 'turnover_d0', 'avg_bet_d0',
       'distinct_games_d0', 'freespin_d0', 'net_d0', 'night_d0']
CAT = ['provider_d0', 'payment_method', 'affiliate_type', 'country']
FEATURES = NUM + CAT

FEATURE_SQL = """
WITH (SELECT toDate(max(created_at)) FROM money_transactions) AS dmax
SELECT
  u.casino_player_id                                                       AS casino_player_id,
  toUInt32(dateDiff('day', toDate(u.ftd_date), dmax))                      AS mat,
  toFloat64(ifNull(u.ftd_amount, 0))                                       AS ftd_amount,
  toFloat64(if(u.reg_date IS NULL, 0, greatest(dateDiff('day', toDate(u.reg_date), toDate(u.ftd_date)), 0))) AS act_lag_days,
  toUInt8(d.n_dep_30 >= 2)                                                  AS made_2nd,
  -- поведение ПЕРВОГО ДНЯ (offset 0 от FTD) — без утечки депозитов
  toFloat64(ifNull(g.bets_d0, 0))            AS bets_d0,
  toFloat64(ifNull(g.turnover_d0, 0))        AS turnover_d0,
  toFloat64(ifNull(g.avg_bet_d0, 0))         AS avg_bet_d0,
  toFloat64(ifNull(g.distinct_games_d0, 0))  AS distinct_games_d0,
  toFloat64(ifNull(g.freespin_d0, 0))        AS freespin_d0,
  toFloat64(ifNull(g.net_d0, 0))             AS net_d0,
  toFloat64(ifNull(g.night_d0, 0))           AS night_d0,
  ifNull(nullIf(g.provider_d0, ''), '(none)')                            AS provider_d0,
  if(u.affiliate_account_type = '', '(none)', u.affiliate_account_type)  AS affiliate_type,
  ifNull(nullIf(pm.payment_method, ''), '(none)')                        AS payment_method,
  ifNull(nullIf(u.country_iso_estimated, ''), '(none)')                  AS country,
  toString(toDate(u.ftd_date))                                           AS ftd_date
FROM users u
INNER JOIN (
  SELECT casino_player_id,
    countIf(toFloat64(amount) >= 0 AND off >= 0 AND off <= 30) AS n_dep_30
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
    countIf(d0)                                          AS bets_d0,
    sumIf(toFloat64(bet_amount), d0)                     AS turnover_d0,
    round(avgIf(toFloat64(bet_amount), d0), 2)           AS avg_bet_d0,
    uniqExactIf(game_uuid, d0)                           AS distinct_games_d0,
    countIf(d0 AND transaction_type = 'freespins_bet')   AS freespin_d0,
    round(sumIf(toFloat64(win_amount), d0) - sumIf(toFloat64(bet_amount), d0), 2) AS net_d0,
    countIf(d0 AND toHour(toTimezone(created_at, 'Europe/Istanbul')) < 6) AS night_d0,
    anyHeavyIf(aggregator, d0)                           AS provider_d0
  FROM (
    SELECT gt.casino_player_id AS casino_player_id, gt.bet_amount, gt.win_amount, gt.game_uuid,
           gt.created_at, gt.transaction_type AS transaction_type, gt.aggregator AS aggregator,
           (gt.transaction_type IN ('bet','freespins_bet','win','freespins_win')
            AND dateDiff('day', toDate(u3.ftd_date), toDate(gt.created_at)) = 0) AS d0
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
        print('SCORE_ONLY: загружаю сохранённую модель repeat (без обучения)')
        final = reg.load('repeat', CatBoostClassifier)
    else:
        mature = df[df['mat'] >= 30].copy().sort_values('ftd_date').reset_index(drop=True)
        base_rate = mature['made_2nd'].mean()
        print(f'  дозревших (mat>=30, для обучения): {len(mature)}  ·  база P(2-й деп)={base_rate:.3f}')

        X = mature[FEATURES]
        y = mature['made_2nd'].values
        split = int(len(mature) * 0.8)
        Xtr, Xte, ytr, yte = X.iloc[:split], X.iloc[split:], y[:split], y[split:]
        print(f'  train={len(Xtr)}  test={len(Xte)} (по времени)')

        model = CatBoostClassifier(iterations=600, depth=5, learning_rate=0.04,
                                   loss_function='Logloss', eval_metric='AUC',
                                   random_seed=42, verbose=False)
        model.fit(Pool(Xtr, ytr, cat_features=cat_idx), eval_set=Pool(Xte, yte, cat_features=cat_idx))

        p_te = model.predict_proba(Pool(Xte, cat_features=cat_idx))[:, 1]
        auc = roc_auc_score(yte, p_te)
        pr = average_precision_score(yte, p_te)
        brier = brier_score_loss(yte, p_te)
        print('\n=== КАЧЕСТВО (test, по времени) ===')
        print(f'  ROC-AUC    : {auc:.3f}  (0.5=угадайка, 1.0=идеал)')
        print(f'  PR-AUC     : {pr:.3f}  (база {yte.mean():.3f})')
        print(f'  Brier      : {brier:.3f}  (калибровка, меньше=лучше)')

        order = np.argsort(-p_te)
        for k in (0.1, 0.2):
            top = order[:max(1, int(len(order) * k))]
            prec = yte[top].mean()
            print(f'  Top-{int(k*100)}% по P: реально сделали 2-й деп {prec*100:.0f}%  (lift ×{prec/yte.mean():.1f})')

        print('\n=== ВАЖНОСТЬ ФИЧ (топ-10) ===')
        for name, v in sorted(zip(FEATURES, model.get_feature_importance()), key=lambda t: -t[1])[:10]:
            print(f'  {name:20s} {v:5.1f}')

        final = CatBoostClassifier(iterations=600, depth=5, learning_rate=0.04,
                                   loss_function='Logloss', random_seed=42, verbose=False)
        final.fit(Pool(X, y, cat_features=cat_idx))
        reg.save('repeat', final, features=FEATURES, cat_features=CAT,
                 metrics={'roc_auc': round(float(auc), 3), 'pr_auc': round(float(pr), 3),
                          'brier': round(float(brier), 3)},
                 extra={'target': '2nd_deposit_within_30d', 'table': 'player_repeat_ml'})
    df['p_2nd_ml'] = final.predict_proba(Pool(df[FEATURES], cat_features=cat_idx))[:, 1].round(4)

    out = df[['casino_player_id', 'p_2nd_ml']].copy()
    out['casino_player_id'] = out['casino_player_id'].astype('uint32')
    out['p_2nd_ml'] = out['p_2nd_ml'].astype('float64')
    client.command('DROP TABLE IF EXISTS player_repeat_ml')
    client.command('CREATE TABLE player_repeat_ml (casino_player_id UInt32, p_2nd_ml Float64) '
                   'ENGINE = MergeTree ORDER BY casino_player_id')
    client.insert_df('player_repeat_ml', out)
    print(f'\n✅ записано вероятностей в retention.player_repeat_ml: {len(out)}')


if __name__ == '__main__':
    main()
