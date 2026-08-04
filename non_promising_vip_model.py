"""
Non-Promising VIP Filtering — аналог модели Mico «stable-vip» / non-promising.
Предсказывает, что VIP начального тира НЕ поднимется на более высокий VIP-тир
за 90 дней (останется/упадёт). Освобождает VIP-менеджеров от бесперспективных.

VIP-уровень на T и на T+90 восстанавливаем из накопительных депозитов (правила казино):
метка = vip_level(T+90) <= vip_level(T)  →  non_promising=1.
Население: vip_level_at_T IN (1,2) (Silver/Gold — есть куда расти).
Фичи (created_at < T): депозит/оборот momentum + расстояние до след. тира + стаж.
Валидация по времени.

Запуск:  .venv/bin/python non_promising_vip_model.py
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

H = 90
# срезы так, чтобы T+90 попадал в данные (до июня)
T_TRAIN = ['2026-01-15', '2026-02-01', '2026-02-15', '2026-03-01']
T_TEST = '2026-03-15'                                   # T+90 = 2026-06-13

NUM = ['vip_level_at_T', 'cum_dep_T', 'dist_to_next_tier', 'dep_recency', 'days_since_ftd',
       'dep_count_30d', 'dep_count_90d', 'dep_sum_30d', 'dep_sum_90d', 'dep_momentum_30v30',
       'avg_deposit', 'max_deposit', 'turnover_30d', 'turnover_90d', 'turnover_momentum',
       'bets_30d', 'active_days_30d', 'wd_sum_90d', 'bonus_sum_90d', 'bet_recency']
CAT = ['country', 'affiliate_type', 'payment_method']
FEATURES = NUM + CAT

DEP = "type='deposit' AND status IN ('completed','approved','success')"
DEP_TRY = DEP + " AND currency='TRY'"
BET = "transaction_type IN ('bet','freespins_bet')"
# пороги тиров для расстояния до следующего
NEXT = "multiIf(cum_dep_T>=500000,1000000, cum_dep_T>=150000,500000, cum_dep_T>=50000,150000, cum_dep_T>=100,50000, 100)"


def vip_expr(cum, mx):
    return (f"multiIf({mx}<100 OR {cum}<100,0, {cum}>=1000000,5, {cum}>=500000,4, "
            f"{cum}>=150000,3, {cum}>=50000,2, 1)")


SQL = f"""
WITH toDate('{{T}}') AS T
SELECT
  m.casino_player_id                                            AS casino_player_id,
  toUInt8({vip_expr('ifNull(fut.cum_dep_T90,0)','ifNull(fut.max_dep_T90,0)')} <= m.vip_level_at_T) AS non_promising,
  m.vip_level_at_T                                              AS vip_level_at_T,
  m.cum_dep_T                                                   AS cum_dep_T,
  round(({NEXT.replace('cum_dep_T','m.cum_dep_T')}) - m.cum_dep_T, 2)  AS dist_to_next_tier,
  m.dep_recency                                                AS dep_recency,
  m.days_since_ftd                                             AS days_since_ftd,
  m.dep_count_30d                                              AS dep_count_30d,
  m.dep_count_90d                                              AS dep_count_90d,
  m.dep_sum_30d                                                AS dep_sum_30d,
  m.dep_sum_90d                                                AS dep_sum_90d,
  round(m.dep_sum_30d / nullIf(m.dep_sum_prev30, 0), 3)        AS dep_momentum_30v30,
  m.avg_deposit                                               AS avg_deposit,
  m.max_deposit                                               AS max_deposit,
  toFloat64(ifNull(g.turnover_30d, 0))                         AS turnover_30d,
  toFloat64(ifNull(g.turnover_90d, 0))                         AS turnover_90d,
  round(ifNull(g.turnover_30d,0) / nullIf(g.turnover_prev30, 0), 3) AS turnover_momentum,
  ifNull(g.bets_30d, 0)                                        AS bets_30d,
  ifNull(g.active_days_30d, 0)                                 AS active_days_30d,
  m.wd_sum_90d                                                 AS wd_sum_90d,
  m.bonus_sum_90d                                              AS bonus_sum_90d,
  ifNull(g.bet_recency, 9999)                                  AS bet_recency,
  ifNull(nullIf(u.country_iso_estimated, ''), '(none)')       AS country,
  if(u.affiliate_account_type = '', '(none)', u.affiliate_account_type) AS affiliate_type,
  ifNull(nullIf(m.payment_method, ''), '(none)')              AS payment_method
FROM (
  SELECT casino_player_id,
    round(sumIf(amount, {DEP_TRY} AND toDate(created_at) < T), 2)  AS cum_dep_T,
    {vip_expr('round(sumIf(amount, ' + DEP_TRY + ' AND toDate(created_at) < T),2)', 'round(maxIf(amount, ' + DEP_TRY + ' AND toDate(created_at) < T),2)')} AS vip_level_at_T,
    countIf({DEP} AND toDate(created_at) < T AND toDate(created_at) > T - 30)  AS dep_count_30d,
    countIf({DEP} AND toDate(created_at) < T AND toDate(created_at) > T - 90)  AS dep_count_90d,
    round(sumIf(amount, {DEP} AND toDate(created_at) < T AND toDate(created_at) > T - 30), 2) AS dep_sum_30d,
    round(sumIf(amount, {DEP} AND toDate(created_at) < T AND toDate(created_at) > T - 90), 2) AS dep_sum_90d,
    round(sumIf(amount, {DEP} AND toDate(created_at) <= T - 30 AND toDate(created_at) > T - 60), 2) AS dep_sum_prev30,
    round(avgIf(amount, {DEP} AND toDate(created_at) < T), 2)      AS avg_deposit,
    round(maxIf(amount, {DEP} AND toDate(created_at) < T), 2)      AS max_deposit,
    dateDiff('day', maxIf(toDate(created_at), {DEP} AND toDate(created_at) < T), T) AS dep_recency,
    dateDiff('day', minIf(toDate(created_at), {DEP} AND toDate(created_at) < T), T) AS days_since_ftd,
    round(sumIf(abs(amount), type='withdrawal' AND status IN ('completed','approved','success') AND toDate(created_at) < T AND toDate(created_at) > T - 90), 2) AS wd_sum_90d,
    round(sumIf(abs(amount), type IN ('bonus','manual_bonus','freespin') AND status IN ('completed','approved','success') AND toDate(created_at) < T AND toDate(created_at) > T - 90), 2) AS bonus_sum_90d,
    anyHeavyIf(payment_method, {DEP} AND toDate(created_at) < T AND payment_method != '' AND payment_method NOT LIKE 'campaign:%') AS payment_method
  FROM retention.money_transactions
  WHERE casino_player_id IN (SELECT casino_player_id FROM retention.users WHERE account_type='normal')
  GROUP BY casino_player_id
) m
LEFT JOIN (
  SELECT casino_player_id,
    round(sumIf(amount, {DEP_TRY} AND toDate(created_at) < T + {H}), 2) AS cum_dep_T90,
    round(maxIf(amount, {DEP_TRY} AND toDate(created_at) < T + {H}), 2) AS max_dep_T90
  FROM retention.money_transactions GROUP BY casino_player_id
) fut USING (casino_player_id)
LEFT JOIN (
  SELECT casino_player_id,
    round(sumIf(bet_amount, {BET} AND toDate(created_at) < T AND toDate(created_at) > T - 30), 2) AS turnover_30d,
    round(sumIf(bet_amount, {BET} AND toDate(created_at) < T AND toDate(created_at) > T - 90), 2) AS turnover_90d,
    round(sumIf(bet_amount, {BET} AND toDate(created_at) <= T - 30 AND toDate(created_at) > T - 60), 2) AS turnover_prev30,
    countIf({BET} AND toDate(created_at) < T AND toDate(created_at) > T - 30) AS bets_30d,
    uniqExactIf(toDate(created_at), {BET} AND toDate(created_at) < T AND toDate(created_at) > T - 30) AS active_days_30d,
    dateDiff('day', maxIf(toDate(created_at), {BET} AND toDate(created_at) < T), T) AS bet_recency
  FROM retention.game_transactions WHERE status='completed' GROUP BY casino_player_id
) g USING (casino_player_id)
INNER JOIN retention.users u USING (casino_player_id)
WHERE m.vip_level_at_T IN (1, 2)
"""


def snapshot(client, T):
    df = client.query_df(SQL.format(T=T))
    df['T'] = T
    return df


def main():
    client = clickhouse_connect.get_client(**CH)
    print(f'Non-Promising VIP: цель = НЕ подняться на тир выше за {H} дней (население Silver/Gold)')
    cat_idx = [FEATURES.index(c) for c in CAT]

    if reg.score_only():
        # SCORE_ONLY: готовый .cbm без переобучения (обучение собирало срезы +
        # два fit — впустую каждый тик). Скоринг ниже общий для обоих режимов.
        print('SCORE_ONLY: загружаю сохранённую модель non_promising_vip (без обучения)')
        final = reg.load('non_promising_vip', CatBoostClassifier)
    else:
        frames = []
        for T in T_TRAIN + [T_TEST]:
            d = snapshot(client, T)
            for c in CAT:
                d[c] = d[c].astype(str)
            print(f'  T={T}: {len(d):5d} VIP · non-promising base {d.non_promising.mean():.3f} (выросли {int((1-d.non_promising).sum())})')
            frames.append(d)
        data = pd.concat(frames, ignore_index=True)

        tr = data[data['T'].isin(T_TRAIN)]
        te = data[data['T'] == T_TEST]
        print(f'\n  train={len(tr)}  test={len(te)}')

        model = CatBoostClassifier(iterations=600, depth=5, learning_rate=0.04, loss_function='Logloss',
                                   eval_metric='AUC', random_seed=42, verbose=False)
        model.fit(Pool(tr[FEATURES], tr['non_promising'].values, cat_features=cat_idx),
                  eval_set=Pool(te[FEATURES], te['non_promising'].values, cat_features=cat_idx))
        p_te = model.predict_proba(Pool(te[FEATURES], cat_features=cat_idx))[:, 1]
        auc = roc_auc_score(te['non_promising'], p_te)
        pr = average_precision_score(te['non_promising'], p_te)
        brier = brier_score_loss(te['non_promising'], p_te)
        print('\n=== КАЧЕСТВО Non-Promising VIP (test по времени) ===')
        print(f'  non-promising base : {te.non_promising.mean():.3f}')
        print(f'  ROC-AUC : {auc:.3f}')
        print(f'  PR-AUC  : {pr:.3f}')
        print(f'  Brier   : {brier:.3f}')
        # для этой модели ценно ранжирование ПЕРСПЕКТИВНЫХ (низкий скор = вырастет)
        order = np.argsort(p_te)  # по возрастанию: топ = самые перспективные
        for k in (0.1, 0.2):
            top = order[:max(1, int(len(order) * k))]
            prog = (1 - te['non_promising'].values[top]).mean()
            base_prog = (1 - te['non_promising']).mean()
            print(f'  Bottom-{int(k*100)}% по скору (самые перспективные): реально выросли {prog*100:.0f}%  (lift ×{prog/max(base_prog,1e-9):.1f})')
        print('\n=== ВАЖНОСТЬ ФИЧ (топ-12) ===')
        for name, v in sorted(zip(FEATURES, model.get_feature_importance()), key=lambda t: -t[1])[:12]:
            print(f'  {name:20s} {v:5.1f}')

        final = CatBoostClassifier(iterations=600, depth=5, learning_rate=0.04, loss_function='Logloss',
                                   random_seed=42, verbose=False)
        final.fit(Pool(data[FEATURES], data['non_promising'].values, cat_features=cat_idx))
        reg.save('non_promising_vip', final, features=FEATURES, cat_features=CAT,
                 metrics={'roc_auc': round(float(auc), 3), 'pr_auc': round(float(pr), 3), 'brier': round(float(brier), 3)},
             extra={'target': f'no_tier_progression_within_{H}d', 'population': 'vip_level in (1,2)',
                    'table': 'player_non_promising_vip_ml', 'horizon_days': H})

    # скоринг текущих Silver/Gold на макс дате
    dmax = client.query("SELECT toString(toDate(max(created_at))) FROM retention.money_transactions").result_rows[0][0]
    scdf = snapshot(client, dmax)
    for c in CAT:
        scdf[c] = scdf[c].astype(str)
    scdf['p_non_promising'] = final.predict_proba(Pool(scdf[FEATURES], cat_features=cat_idx))[:, 1].round(4)
    out = scdf[['casino_player_id', 'p_non_promising']].copy()
    out['casino_player_id'] = out['casino_player_id'].astype('uint32')
    out['p_non_promising'] = out['p_non_promising'].astype('float64')
    client.command('DROP TABLE IF EXISTS retention.player_non_promising_vip_ml')
    client.command('CREATE TABLE retention.player_non_promising_vip_ml (casino_player_id UInt32, p_non_promising Float64) '
                   'ENGINE = MergeTree ORDER BY casino_player_id')
    client.insert_df('player_non_promising_vip_ml', out)
    print(f'\n✅ скоринг текущих Silver/Gold → retention.player_non_promising_vip_ml: {len(out)}')


if __name__ == '__main__':
    main()
