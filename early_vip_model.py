"""
Early-VIP Identification — аналог модели Mico «early-vip».
Предсказывает по поведению ПЕРВОЙ НЕДЕЛИ (день 0–7 от FTD), станет ли игрок VIP
(достигнет Gold: накопит ≥50 000 TRY успешных депозитов) в течение 90 дней.

Защита от утечки: фичи только из окна [FTD, FTD+7]; метка — из [FTD, FTD+90].
Население: депозиторы (normal), у кого FTD+90 <= max данных (метка наблюдаема).
Валидация по времени (ранние FTD → train, поздние → test).
Скоринг: все депозиторы -> retention.player_early_vip_ml (P стать VIP).

Запуск:  .venv/bin/python early_vip_model.py
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

VIP_THRESHOLD = 50000   # Gold
HORIZON = 90

NUM = ['ftd_amount', 'act_lag_days', 'dep_d0', 'dep_d7', 'ndep_d7', 'max_dep_d7', 'wd_d7',
       'bets_d7', 'turnover_d7', 'avg_bet_d7', 'distinct_games_d7', 'active_days_d7',
       'freespin_d7', 'night_d7', 'net_d7']
CAT = ['provider_d7', 'payment_method', 'affiliate_type', 'country']
FEATURES = NUM + CAT

DEP = "type='deposit' AND status IN ('completed','approved','success')"
DEP_TRY = DEP + " AND currency='TRY'"
WD = "type='withdrawal' AND status IN ('completed','approved','success')"
BET = "transaction_type IN ('bet','freespins_bet')"

SQL = f"""
WITH (SELECT toDate(max(created_at)) FROM retention.money_transactions) AS dmax
SELECT
  u.casino_player_id                                                       AS casino_player_id,
  toUInt8(ifNull(d.label_cum_90, 0) >= {VIP_THRESHOLD})                     AS reached_vip,
  toUInt32(dateDiff('day', toDate(u.ftd_date), dmax))                       AS mat,
  toFloat64(ifNull(u.ftd_amount, 0))                                        AS ftd_amount,
  toFloat64(if(u.reg_date IS NULL, 0, greatest(dateDiff('day', toDate(u.reg_date), toDate(u.ftd_date)), 0))) AS act_lag_days,
  toFloat64(ifNull(d.dep_d0, 0))            AS dep_d0,
  toFloat64(ifNull(d.dep_d7, 0))            AS dep_d7,
  toFloat64(ifNull(d.ndep_d7, 0))           AS ndep_d7,
  toFloat64(ifNull(d.max_dep_d7, 0))        AS max_dep_d7,
  toFloat64(ifNull(d.wd_d7, 0))             AS wd_d7,
  toFloat64(ifNull(g.bets_d7, 0))           AS bets_d7,
  toFloat64(ifNull(g.turnover_d7, 0))       AS turnover_d7,
  toFloat64(ifNull(g.avg_bet_d7, 0))        AS avg_bet_d7,
  toFloat64(ifNull(g.distinct_games_d7, 0)) AS distinct_games_d7,
  toFloat64(ifNull(g.active_days_d7, 0))    AS active_days_d7,
  toFloat64(ifNull(g.freespin_d7, 0))       AS freespin_d7,
  toFloat64(ifNull(g.night_d7, 0))          AS night_d7,
  toFloat64(ifNull(g.net_d7, 0))            AS net_d7,
  ifNull(nullIf(g.provider_d7, ''), '(none)')                            AS provider_d7,
  ifNull(nullIf(pm.payment_method, ''), '(none)')                        AS payment_method,
  if(u.affiliate_account_type = '', '(none)', u.affiliate_account_type)  AS affiliate_type,
  ifNull(nullIf(u.country_iso_estimated, ''), '(none)')                  AS country,
  toString(toDate(u.ftd_date))                                           AS ftd_date
FROM retention.users u
INNER JOIN (
  SELECT casino_player_id,
    sumIf(amount, {DEP_TRY} AND off BETWEEN 0 AND {HORIZON})              AS label_cum_90,
    sumIf(amount, {DEP} AND off = 0)                                      AS dep_d0,
    sumIf(amount, {DEP} AND off BETWEEN 0 AND 7)                          AS dep_d7,
    countIf({DEP} AND off BETWEEN 0 AND 7)                                AS ndep_d7,
    maxIf(amount, {DEP} AND off BETWEEN 0 AND 7)                          AS max_dep_d7,
    countIf({WD} AND off BETWEEN 0 AND 7)                                 AS wd_d7
  FROM (
    SELECT m.casino_player_id AS casino_player_id, m.type AS type, m.status AS status,
           m.amount AS amount, m.currency AS currency,
           dateDiff('day', toDate(u2.ftd_date), toDate(m.created_at)) AS off
    FROM retention.money_transactions m INNER JOIN retention.users u2 USING (casino_player_id)
    WHERE u2.account_type='normal' AND u2.ftd_date IS NOT NULL
  ) GROUP BY casino_player_id
) d USING (casino_player_id)
LEFT JOIN (
  SELECT casino_player_id,
    countIf(d0w)                                          AS bets_d7,
    round(sumIf(toFloat64(bet_amount), d0w), 2)           AS turnover_d7,
    round(avgIf(toFloat64(bet_amount), d0w), 2)           AS avg_bet_d7,
    uniqExactIf(game_uuid, d0w)                           AS distinct_games_d7,
    uniqExactIf(toDate(created_at), d0w)                  AS active_days_d7,
    countIf(d0w AND transaction_type='freespins_bet')     AS freespin_d7,
    countIf(d0w AND toHour(toTimezone(created_at,'Europe/Istanbul'))<6) AS night_d7,
    round(sumIf(toFloat64(win_amount), d0w) - sumIf(toFloat64(bet_amount), d0w), 2) AS net_d7,
    anyHeavyIf(aggregator, d0w)                           AS provider_d7
  FROM (
    SELECT gt.casino_player_id AS casino_player_id, gt.bet_amount, gt.win_amount, gt.game_uuid,
           gt.created_at, gt.transaction_type AS transaction_type, gt.aggregator AS aggregator,
           (gt.transaction_type IN ('bet','freespins_bet','win','freespins_win')
            AND dateDiff('day', toDate(u3.ftd_date), toDate(gt.created_at)) BETWEEN 0 AND 7) AS d0w
    FROM retention.game_transactions gt INNER JOIN retention.users u3 USING (casino_player_id)
    WHERE gt.status='completed' AND u3.account_type='normal' AND u3.ftd_date IS NOT NULL
  ) GROUP BY casino_player_id
) g USING (casino_player_id)
LEFT JOIN (
  SELECT casino_player_id,
    anyHeavyIf(payment_method, {DEP} AND payment_method != '' AND payment_method NOT LIKE 'campaign:%') AS payment_method
  FROM retention.money_transactions GROUP BY casino_player_id
) pm USING (casino_player_id)
WHERE u.account_type='normal' AND u.ftd_date IS NOT NULL
"""


def main():
    client = clickhouse_connect.get_client(**CH)
    print(f'Early-VIP: цель = накопить ≥{VIP_THRESHOLD:,} TRY (Gold) за {HORIZON} дней от FTD')
    df = client.query_df(SQL)
    for c in CAT:
        df[c] = df[c].astype(str)
    cat_idx = [FEATURES.index(c) for c in CAT]

    if reg.score_only():
        # SCORE_ONLY: готовый .cbm без переобучения. Скоринг ниже (по всему df) —
        # общий для обоих режимов.
        print('SCORE_ONLY: загружаю сохранённую модель early_vip (без обучения)')
        final = reg.load('early_vip', CatBoostClassifier)
    else:
        mature = df[df['mat'] >= HORIZON].copy().sort_values('ftd_date').reset_index(drop=True)
        base = mature['reached_vip'].mean()
        print(f'  всего депозиторов: {len(df)}  ·  дозревших (mat>={HORIZON}): {len(mature)}')
        print(f'  стали VIP (Gold): {int(mature.reached_vip.sum())}  ·  база {base:.3f}')

        split = int(len(mature) * 0.8)
        tr, te = mature.iloc[:split], mature.iloc[split:]
        print(f'  train={len(tr)}  test={len(te)} (по времени)  ·  VIP в test: {int(te.reached_vip.sum())}')

        model = CatBoostClassifier(iterations=600, depth=5, learning_rate=0.04, loss_function='Logloss',
                                   eval_metric='AUC', random_seed=42, verbose=False,
                                   auto_class_weights='Balanced')
        model.fit(Pool(tr[FEATURES], tr['reached_vip'].values, cat_features=cat_idx),
                  eval_set=Pool(te[FEATURES], te['reached_vip'].values, cat_features=cat_idx))
        p_te = model.predict_proba(Pool(te[FEATURES], cat_features=cat_idx))[:, 1]
        auc = roc_auc_score(te['reached_vip'], p_te)
        pr = average_precision_score(te['reached_vip'], p_te)
        brier = brier_score_loss(te['reached_vip'], p_te)
        print('\n=== КАЧЕСТВО Early-VIP (test по времени) ===')
        print(f'  base VIP-rate : {te.reached_vip.mean():.3f}')
        print(f'  ROC-AUC : {auc:.3f}')
        print(f'  PR-AUC  : {pr:.3f}  (база {te.reached_vip.mean():.3f})')
        print(f'  Brier   : {brier:.3f}')
        order = np.argsort(-p_te)
        for k in (0.05, 0.1, 0.2):
            top = order[:max(1, int(len(order) * k))]
            prec = te['reached_vip'].values[top].mean()
            print(f'  Top-{int(k*100)}% по скору: реально VIP {prec*100:.0f}%  (lift ×{prec/max(te.reached_vip.mean(),1e-9):.1f})')
        print('\n=== ВАЖНОСТЬ ФИЧ (топ-12) ===')
        for name, v in sorted(zip(FEATURES, model.get_feature_importance()), key=lambda t: -t[1])[:12]:
            print(f'  {name:20s} {v:5.1f}')

        final = CatBoostClassifier(iterations=600, depth=5, learning_rate=0.04, loss_function='Logloss',
                                   random_seed=42, verbose=False, auto_class_weights='Balanced')
        final.fit(Pool(mature[FEATURES], mature['reached_vip'].values, cat_features=cat_idx))
        reg.save('early_vip', final, features=FEATURES, cat_features=CAT,
                 metrics={'roc_auc': round(float(auc), 3), 'pr_auc': round(float(pr), 3), 'brier': round(float(brier), 3)},
                 extra={'target': f'reach_gold_{VIP_THRESHOLD}_within_{HORIZON}d', 'table': 'player_early_vip_ml'})

    df['p_early_vip'] = final.predict_proba(Pool(df[FEATURES], cat_features=cat_idx))[:, 1].round(4)
    out = df[['casino_player_id', 'p_early_vip']].copy()
    out['casino_player_id'] = out['casino_player_id'].astype('uint32')
    out['p_early_vip'] = out['p_early_vip'].astype('float64')
    client.command('DROP TABLE IF EXISTS retention.player_early_vip_ml')
    client.command('CREATE TABLE retention.player_early_vip_ml (casino_player_id UInt32, p_early_vip Float64) '
                   'ENGINE = MergeTree ORDER BY casino_player_id')
    client.insert_df('player_early_vip_ml', out)
    print(f'\n✅ скоринг → retention.player_early_vip_ml: {len(out)}')


if __name__ == '__main__':
    main()
