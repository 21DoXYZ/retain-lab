"""
VIP-Churn (депозитный отток) — аналог флагманской модели Mico.
Отличие от нашего churn_model.py: отток определяется по ДЕПОЗИТАМ (не по ставкам),
население — только VIP. VIP-уровень на дату T восстанавливаем из накопительных
успешных депозитов TRY (правила казино) — своя VIP-история, без внешнего фида.

- Население на T: vip_level_at_T >= 1 (Silver+) И депозит был за последние 45 дней (ещё активен).
- Метка: НЕ сделал НИ ОДНОГО успешного депозита в (T, T+H].  H=30.
- Фичи (created_at < T): депозитная RFM + игровая активность + бонусы + стаж. Защита от утечки.
- Валидация по времени: ранние срезы → train, поздний → test.
- Скоринг: срез на максимум данных → P(deposit-churn) текущих VIP → retention.player_vip_churn_ml.

Запуск:  .venv/bin/python vip_churn_model.py
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
# срезы до июля (свежие депозиты чистые; июль имеет пробелы в потоке)
T_TRAIN = ['2026-02-15', '2026-03-01', '2026-03-15', '2026-04-01', '2026-04-15']
T_TEST = '2026-05-15'                                   # T+30 = 2026-06-15 (в данных)

NUM = ['vip_level_at_T', 'cum_dep_T', 'dep_recency', 'days_since_ftd',
       'dep_count_life', 'dep_count_30d', 'dep_count_90d', 'dep_sum_30d', 'dep_sum_90d',
       'avg_deposit', 'max_deposit', 'mean_dep_gap', 'dep_overdue_ratio', 'dep_momentum_30v30',
       'failed_dep_90d', 'wd_count_90d', 'wd_sum_90d', 'bonus_count_90d', 'bonus_sum_90d',
       'bets_30d', 'turnover_30d', 'active_days_30d', 'bet_recency', 'bets_momentum_7v7']
CAT = ['country', 'affiliate_type', 'payment_method']
FEATURES = NUM + CAT

DEPF = "type='deposit' AND status IN ('completed','approved','success')"
DEPF_TRY = DEPF + " AND currency='TRY'"
BET = "transaction_type IN ('bet','freespins_bet')"

SNAP = f"""
WITH toDate('{{T}}') AS T
SELECT
  m.casino_player_id                                            AS casino_player_id,
  toUInt8(ifNull(fut.dep_after, 0) = 0)                         AS churned,
  multiIf(m.max_dep_T<100 OR m.cum_dep_T<100,0, m.cum_dep_T>=1000000,5, m.cum_dep_T>=500000,4,
          m.cum_dep_T>=150000,3, m.cum_dep_T>=50000,2, 1)       AS vip_level_at_T,
  m.cum_dep_T                                                   AS cum_dep_T,
  m.dep_recency                                                 AS dep_recency,
  m.days_since_ftd                                              AS days_since_ftd,
  m.dep_count_life                                              AS dep_count_life,
  m.dep_count_30d                                               AS dep_count_30d,
  m.dep_count_90d                                               AS dep_count_90d,
  m.dep_sum_30d                                                 AS dep_sum_30d,
  m.dep_sum_90d                                                 AS dep_sum_90d,
  m.avg_deposit                                                 AS avg_deposit,
  m.max_deposit                                                 AS max_deposit,
  round((m.days_since_ftd - m.dep_recency) / greatest(m.dep_count_life - 1, 1), 2) AS mean_dep_gap,
  round(m.dep_recency / nullIf((m.days_since_ftd - m.dep_recency) / greatest(m.dep_count_life - 1, 1), 0), 3) AS dep_overdue_ratio,
  round(m.dep_sum_30d / nullIf(m.dep_sum_prev30, 0), 3)         AS dep_momentum_30v30,
  m.failed_dep_90d                                              AS failed_dep_90d,
  m.wd_count_90d                                                AS wd_count_90d,
  m.wd_sum_90d                                                  AS wd_sum_90d,
  m.bonus_count_90d                                             AS bonus_count_90d,
  m.bonus_sum_90d                                               AS bonus_sum_90d,
  ifNull(g.bets_30d, 0)                                         AS bets_30d,
  toFloat64(ifNull(g.turnover_30d, 0))                          AS turnover_30d,
  ifNull(g.active_days_30d, 0)                                  AS active_days_30d,
  ifNull(g.bet_recency, 9999)                                   AS bet_recency,
  round(ifNull(g.bets_7d, 0) / nullIf(g.bets_prev7, 0), 3)      AS bets_momentum_7v7,
  ifNull(nullIf(u.country_iso_estimated, ''), '(none)')        AS country,
  if(u.affiliate_account_type = '', '(none)', u.affiliate_account_type) AS affiliate_type,
  ifNull(nullIf(m.payment_method, ''), '(none)')               AS payment_method
FROM (
  SELECT casino_player_id,
    round(sumIf(amount, {DEPF_TRY} AND toDate(created_at) < T), 2)  AS cum_dep_T,
    round(maxIf(amount, {DEPF_TRY} AND toDate(created_at) < T), 2)  AS max_dep_T,
    countIf({DEPF} AND toDate(created_at) < T)                      AS dep_count_life,
    countIf({DEPF} AND toDate(created_at) < T AND toDate(created_at) > T - 30)  AS dep_count_30d,
    countIf({DEPF} AND toDate(created_at) < T AND toDate(created_at) > T - 90)  AS dep_count_90d,
    round(sumIf(amount, {DEPF} AND toDate(created_at) < T AND toDate(created_at) > T - 30), 2) AS dep_sum_30d,
    round(sumIf(amount, {DEPF} AND toDate(created_at) < T AND toDate(created_at) > T - 90), 2) AS dep_sum_90d,
    round(sumIf(amount, {DEPF} AND toDate(created_at) <= T - 30 AND toDate(created_at) > T - 60), 2) AS dep_sum_prev30,
    round(avgIf(amount, {DEPF} AND toDate(created_at) < T), 2)      AS avg_deposit,
    round(maxIf(amount, {DEPF} AND toDate(created_at) < T), 2)      AS max_deposit,
    dateDiff('day', maxIf(toDate(created_at), {DEPF} AND toDate(created_at) < T), T) AS dep_recency,
    dateDiff('day', minIf(toDate(created_at), {DEPF} AND toDate(created_at) < T), T) AS days_since_ftd,
    countIf(type='deposit' AND status IN ('rejected','failed') AND toDate(created_at) < T AND toDate(created_at) > T - 90) AS failed_dep_90d,
    countIf(type='withdrawal' AND status IN ('completed','approved','success') AND toDate(created_at) < T AND toDate(created_at) > T - 90) AS wd_count_90d,
    round(sumIf(abs(amount), type='withdrawal' AND status IN ('completed','approved','success') AND toDate(created_at) < T AND toDate(created_at) > T - 90), 2) AS wd_sum_90d,
    countIf(type IN ('bonus','manual_bonus','freespin') AND status IN ('completed','approved','success') AND toDate(created_at) < T AND toDate(created_at) > T - 90) AS bonus_count_90d,
    round(sumIf(abs(amount), type IN ('bonus','manual_bonus','freespin') AND status IN ('completed','approved','success') AND toDate(created_at) < T AND toDate(created_at) > T - 90), 2) AS bonus_sum_90d,
    anyHeavyIf(payment_method, {DEPF} AND toDate(created_at) < T AND payment_method != '' AND payment_method NOT LIKE 'campaign:%') AS payment_method
  FROM retention.money_transactions
  WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal')
  GROUP BY casino_player_id
  HAVING dep_count_life >= 1
) m
LEFT JOIN (
  SELECT casino_player_id, countIf({DEPF} AND toDate(created_at) >= T AND toDate(created_at) < T + {H}) AS dep_after
  FROM retention.money_transactions GROUP BY casino_player_id
) fut USING (casino_player_id)
LEFT JOIN (
  SELECT casino_player_id,
    countIf({BET} AND toDate(created_at) < T AND toDate(created_at) > T - 30) AS bets_30d,
    round(sumIf(bet_amount, {BET} AND toDate(created_at) < T AND toDate(created_at) > T - 30), 2) AS turnover_30d,
    uniqExactIf(toDate(created_at), {BET} AND toDate(created_at) < T AND toDate(created_at) > T - 30) AS active_days_30d,
    dateDiff('day', maxIf(toDate(created_at), {BET} AND toDate(created_at) < T), T) AS bet_recency,
    countIf({BET} AND toDate(created_at) < T AND toDate(created_at) > T - 7) AS bets_7d,
    countIf({BET} AND toDate(created_at) <= T - 7 AND toDate(created_at) > T - 14) AS bets_prev7
  FROM retention.game_transactions WHERE status='completed' GROUP BY casino_player_id
) g USING (casino_player_id)
INNER JOIN retention.users u USING (casino_player_id)
WHERE (multiIf(m.max_dep_T<100 OR m.cum_dep_T<100,0, m.cum_dep_T>=1000000,5, m.cum_dep_T>=500000,4,
               m.cum_dep_T>=150000,3, m.cum_dep_T>=50000,2, 1)) >= 1
  AND m.dep_recency <= 45
"""


def snapshot(client, T):
    df = client.query_df(SNAP.format(T=T))
    df['T'] = T
    return df


def main():
    client = clickhouse_connect.get_client(**CH)
    dmax = client.query("SELECT toString(toDate(max(created_at))) FROM retention.money_transactions").result_rows[0][0]
    print(f'данные до: {dmax}  ·  горизонт H={H} (отток = 0 депозитов за {H} дней)')
    cat_idx = [FEATURES.index(c) for c in CAT]

    if reg.score_only():
        # SCORE_ONLY: грузим сохранённый .cbm и НЕ переобучаем. Обучение собирало
        # point-in-time срезы и делало два fit (~11с) — впустую каждые 5 мин, ведь
        # за тик данные почти не меняются. Скоринг ниже — общий для обоих режимов.
        print('SCORE_ONLY: загружаю сохранённую модель vip_churn (без обучения)')
        final = reg.load('vip_churn', CatBoostClassifier)
    else:
        print('Собираю срезы VIP (point-in-time)...')
        frames = []
        for T in T_TRAIN + [T_TEST]:
            d = snapshot(client, T)
            for c in CAT:
                d[c] = d[c].astype(str)
            print(f'  T={T}: {len(d):5d} VIP · deposit-churn base {d.churned.mean():.3f}')
            frames.append(d)
        data = pd.concat(frames, ignore_index=True)

        tr = data[data['T'].isin(T_TRAIN)]
        te = data[data['T'] == T_TEST]
        print(f'\n  train={len(tr)} (срезы {T_TRAIN})  ·  test={len(te)} (срез {T_TEST})')

        model = CatBoostClassifier(iterations=700, depth=5, learning_rate=0.04,
                                   loss_function='Logloss', eval_metric='AUC', random_seed=42, verbose=False)
        model.fit(Pool(tr[FEATURES], tr['churned'].values, cat_features=cat_idx),
                  eval_set=Pool(te[FEATURES], te['churned'].values, cat_features=cat_idx))

        p_te = model.predict_proba(Pool(te[FEATURES], cat_features=cat_idx))[:, 1]
        auc = roc_auc_score(te['churned'], p_te)
        pr = average_precision_score(te['churned'], p_te)
        brier = brier_score_loss(te['churned'], p_te)
        print('\n=== КАЧЕСТВО VIP-Churn (test = поздний срез) ===')
        print(f'  deposit-churn base : {te.churned.mean():.3f}')
        print(f'  ROC-AUC : {auc:.3f}')
        print(f'  PR-AUC  : {pr:.3f}')
        print(f'  Brier   : {brier:.3f}')
        order = np.argsort(-p_te)
        for k in (0.1, 0.2):
            top = order[:max(1, int(len(order) * k))]
            prec = te['churned'].values[top].mean()
            print(f'  Top-{int(k*100)}% по риску: реально ушли {prec*100:.0f}%  (lift ×{prec/te.churned.mean():.2f})')

        print('\n=== ВАЖНОСТЬ ФИЧ (топ-15) ===')
        for name, v in sorted(zip(FEATURES, model.get_feature_importance()), key=lambda t: -t[1])[:15]:
            print(f'  {name:22s} {v:5.1f}')

        # финальная модель на всех срезах
        final = CatBoostClassifier(iterations=700, depth=5, learning_rate=0.04,
                                   loss_function='Logloss', random_seed=42, verbose=False)
        final.fit(Pool(data[FEATURES], data['churned'].values, cat_features=cat_idx))
        reg.save('vip_churn', final, features=FEATURES, cat_features=CAT,
                 metrics={'roc_auc': round(float(auc), 3), 'pr_auc': round(float(pr), 3), 'brier': round(float(brier), 3)},
                 extra={'target': 'no_deposit_within_30d', 'population': 'vip_level>=1 & dep_recency<=45',
                        'table': 'player_vip_churn_ml', 'horizon_days': H})

    scdf = snapshot(client, dmax)
    for c in CAT:
        scdf[c] = scdf[c].astype(str)
    scdf['p_vip_churn'] = final.predict_proba(Pool(scdf[FEATURES], cat_features=cat_idx))[:, 1].round(4)
    out = scdf[['casino_player_id', 'p_vip_churn']].copy()
    out['casino_player_id'] = out['casino_player_id'].astype('uint32')
    out['p_vip_churn'] = out['p_vip_churn'].astype('float64')
    client.command('DROP TABLE IF EXISTS retention.player_vip_churn_ml')
    client.command('CREATE TABLE retention.player_vip_churn_ml (casino_player_id UInt32, p_vip_churn Float64) '
                   'ENGINE = MergeTree ORDER BY casino_player_id')
    client.insert_df('player_vip_churn_ml', out)
    print(f'\n✅ скоринг текущих VIP → retention.player_vip_churn_ml: {len(out)}  ·  средний риск {out.p_vip_churn.mean():.3f}')


if __name__ == '__main__':
    main()
