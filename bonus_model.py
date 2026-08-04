"""
Бонус-слой (4-я модель): какой ТИП бонуса рекомендовать игроку + квазиэксперимент uplift.

1) Response-модель (S-learner, CatBoost): состояние игрока + тип бонуса -> P(остался активен 30 дней).
   Обучение по ПЕРВОМУ бонусу каждого игрока, фичи «как было ДО бонуса» (без утечки).
   Скоринг: для каждого игрока перебираем типы бонусов -> рекомендуем лучший.
2) Uplift (квазиэксперимент): propensity-matching бонусных vs небонусных депозиторов
   -> directional ATE с бутстреп-CI. Честно: контроль тонкий (227), оценка наблюдательная.

Цель (target) = retention: сыграл хоть раз в (бонус, бонус+30д]. Меньше механического смещения, чем «депозит».

Запуск:  .venv/bin/python bonus_model.py
"""
import os
import numpy as np
import pandas as pd
import clickhouse_connect
from catboost import CatBoostClassifier, Pool
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score
import model_registry as reg

CH = dict(host=os.environ.get('CH_HOST', '127.0.0.1'), port=int(os.environ.get('CH_PORT', '8123')),
          username=os.environ.get('CH_USER', 'default'), password=os.environ.get('CH_PASSWORD', ''),
          database=os.environ.get('CH_DB', 'retention'))

NUM = ['recency_days', 'tenure_days', 'bets', 'turnover', 'active_days', 'avg_bet',
       'freespin_ratio', 'night_share', 'dep_count', 'dep_sum', 'deposit_recency']
CAT = ['provider', 'country', 'affiliate_type', 'bonus_type']
FEATURES = NUM + CAT
BONUS_TYPES = ['freespins', 'deposit-match', 'no-deposit']   # cashback исключён: n=10, моделировать нельзя

BTYPE = ("multiIf(type='freespin','freespins',"
         "description ILIKE '%deneme%','no-deposit',"
         "description ILIKE '%kay%p%','cashback',"
         "description ILIKE '%dsc%' OR description ILIKE '%yat%','deposit-match','other-manual')")

TRAIN_SQL = f"""
WITH
fb AS (
  SELECT casino_player_id, min(created_at) AS fbts, argMin(btype, created_at) AS bonus_type
  FROM (
    SELECT casino_player_id, created_at, {BTYPE} AS btype
    FROM money_transactions WHERE type IN ('freespin','manual_bonus','bonus') AND status='completed'
  ) GROUP BY casino_player_id
)
SELECT
  fb.casino_player_id                          AS casino_player_id,
  fb.bonus_type                                AS bonus_type,
  toUInt8(ifNull(r.played_after,0) > 0)        AS retained,
  toUInt8(ifNull(rd.dep_after,0) > 0)          AS deposited_after,
  ifNull(g.recency_days, 9999)                 AS recency_days,
  ifNull(g.tenure_days, 0)                     AS tenure_days,
  ifNull(g.bets, 0)                            AS bets,
  toFloat64(ifNull(g.turnover, 0))             AS turnover,
  ifNull(g.active_days, 0)                     AS active_days,
  toFloat64(ifNull(g.avg_bet, 0))              AS avg_bet,
  ifNull(g.freespin_ratio, 0)                  AS freespin_ratio,
  ifNull(g.night_share, 0)                     AS night_share,
  ifNull(mm.dep_count, 0)                      AS dep_count,
  toFloat64(ifNull(mm.dep_sum, 0))             AS dep_sum,
  if(ifNull(mm.dep_count,0) > 0, mm.deposit_recency, 9999) AS deposit_recency,
  ifNull(nullIf(g.provider, ''), '(none)')     AS provider,
  ifNull(nullIf(u.country_iso_estimated, ''), '(none)') AS country,
  if(u.affiliate_account_type='', '(none)', u.affiliate_account_type) AS affiliate_type,
  toUInt32(dateDiff('day', toDate(fb.fbts), (SELECT toDate(max(created_at)) FROM money_transactions))) AS mat,
  toString(toDate(fb.fbts))                     AS fb_date
FROM fb
LEFT JOIN (
  SELECT gt.casino_player_id AS casino_player_id,
    dateDiff('day', max(toDate(gt.created_at)), toDate(any(fb.fbts)))       AS recency_days,
    dateDiff('day', min(toDate(gt.created_at)), toDate(any(fb.fbts)))       AS tenure_days,
    count() AS bets, round(sum(toFloat64(gt.bet_amount)),2) AS turnover,
    uniqExact(toDate(gt.created_at)) AS active_days, round(avg(toFloat64(gt.bet_amount)),2) AS avg_bet,
    round(countIf(gt.transaction_type='freespins_bet')/count(),3) AS freespin_ratio,
    round(countIf(toHour(toTimezone(gt.created_at,'Europe/Istanbul'))<6)/count(),3) AS night_share,
    anyHeavy(gt.aggregator) AS provider
  FROM game_transactions gt INNER JOIN fb USING (casino_player_id)
  WHERE gt.transaction_type IN ('bet','freespins_bet') AND gt.created_at < fb.fbts
  GROUP BY gt.casino_player_id
) g USING (casino_player_id)
LEFT JOIN (
  SELECT mt.casino_player_id AS casino_player_id,
    countIf(mt.type IN ('deposit','manual_deposit') AND mt.status='completed') AS dep_count,
    round(sumIf(toFloat64(mt.amount), mt.type IN ('deposit','manual_deposit') AND mt.status='completed'),2) AS dep_sum,
    dateDiff('day', maxIf(toDate(mt.created_at), mt.type IN ('deposit','manual_deposit') AND mt.status='completed'), toDate(any(fb.fbts))) AS deposit_recency
  FROM money_transactions mt INNER JOIN fb USING (casino_player_id)
  WHERE mt.created_at < fb.fbts
  GROUP BY mt.casino_player_id
) mm USING (casino_player_id)
LEFT JOIN (
  SELECT gt.casino_player_id AS casino_player_id, count() AS played_after
  FROM game_transactions gt INNER JOIN fb USING (casino_player_id)
  WHERE gt.transaction_type IN ('bet','freespins_bet')
    AND gt.created_at > fb.fbts AND gt.created_at <= fb.fbts + INTERVAL 30 DAY
  GROUP BY gt.casino_player_id
) r USING (casino_player_id)
LEFT JOIN (
  SELECT mt.casino_player_id AS casino_player_id, count() AS dep_after
  FROM money_transactions mt INNER JOIN fb USING (casino_player_id)
  WHERE mt.type IN ('deposit','manual_deposit') AND mt.status='completed'
    AND mt.created_at > fb.fbts AND mt.created_at <= fb.fbts + INTERVAL 14 DAY
  GROUP BY mt.casino_player_id
) rd USING (casino_player_id)
INNER JOIN users u USING (casino_player_id)
WHERE u.account_type='normal'
"""

SCORE_SQL = """
SELECT casino_player_id,
  ifNull(recency_days,9999) AS recency_days, ifNull(tenure_days,0) AS tenure_days,
  bets, toFloat64(ifNull(turnover,0)) AS turnover, active_days, toFloat64(ifNull(avg_bet,0)) AS avg_bet,
  freespin_ratio, night_share, dep_count, toFloat64(ifNull(dep_sum,0)) AS dep_sum,
  ifNull(deposit_recency_days,9999) AS deposit_recency,
  ifNull(nullIf(primary_provider,''),'(none)') AS provider,
  ifNull(nullIf(country,''),'(none)') AS country,
  ifNull(nullIf(affiliate_type,''),'(none)') AS affiliate_type
FROM player_features
WHERE account_type='normal' AND ever_played
"""


def quasi_uplift(client) -> dict:
    """Propensity-matched directional ATE: бонус -> retention-30 у депозиторов. Контроль тонкий -> с CI."""
    q = f"""
    WITH fb AS (
      SELECT casino_player_id, min(created_at) AS fbts FROM money_transactions
      WHERE type IN ('freespin','manual_bonus','bonus') AND status='completed' GROUP BY casino_player_id
    )
    SELECT u.casino_player_id AS casino_player_id,
      toUInt8(u.casino_player_id IN (SELECT casino_player_id FROM fb)) AS treated,
      toFloat64(ifNull(u.ftd_amount,0)) AS ftd_amount,
      dateDiff('day', toDate(u.reg_date), toDate(u.ftd_date)) AS act_lag,
      toUInt8(ifNull(pf.bets,0) > 0) AS played,
      toFloat64(ifNull(pf.avg_bet,0)) AS avg_bet,
      ifNull(pf.tenure_days,0) AS tenure_days,
      -- исход: активен 30д после FTD
      toUInt8(ifNull(r.played_after,0) > 0) AS retained
    FROM users u
    LEFT JOIN player_features pf USING (casino_player_id)
    LEFT JOIN (
      SELECT gt.casino_player_id AS casino_player_id, count() AS played_after
      FROM game_transactions gt INNER JOIN users uu USING (casino_player_id)
      WHERE gt.transaction_type IN ('bet','freespins_bet')
        AND gt.created_at > toDateTime(uu.ftd_date) AND gt.created_at <= toDateTime(uu.ftd_date) + INTERVAL 30 DAY
      GROUP BY gt.casino_player_id
    ) r USING (casino_player_id)
    WHERE u.account_type='normal' AND u.ftd_date IS NOT NULL
      AND dateDiff('day', toDate(u.ftd_date), (SELECT toDate(max(created_at)) FROM money_transactions)) >= 30
    """
    df = client.query_df(q)
    Xcols = ['ftd_amount', 'act_lag', 'played', 'avg_bet', 'tenure_days']
    df[Xcols] = df[Xcols].fillna(0)
    Xs = StandardScaler().fit_transform(df[Xcols])
    ps = LogisticRegression(max_iter=1000).fit(Xs, df['treated']).predict_proba(Xs)[:, 1]
    df['ps'] = ps
    df['retained'] = df['retained'].astype(float)
    tr = df[df['treated'] == 1].reset_index(drop=True)
    ct = df[df['treated'] == 0].reset_index(drop=True)
    # nearest-neighbour match каждого control к ближайшему по propensity treated (контроль маленький)
    ct_ps = ct['ps'].values
    tr_ps = tr['ps'].values
    tr_ret = tr['retained'].values.astype(float)
    ct_ret = ct['retained'].values.astype(float)
    diffs = np.array([tr_ret[int(np.argmin(np.abs(tr_ps - ct_ps[i])))] - ct_ret[i]
                      for i in range(len(ct))], dtype=float)
    att = diffs.mean()
    boot = [np.random.choice(diffs, len(diffs), replace=True).mean() for _ in range(2000)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return dict(n_treated=int(df['treated'].sum()), n_control=int((1 - df['treated']).sum()),
                retain_treated=float(tr['retained'].mean()), retain_control=float(ct['retained'].mean()),
                att=float(att), ci_lo=float(lo), ci_hi=float(hi))


def main() -> None:
    np.random.seed(42)
    client = clickhouse_connect.get_client(**CH)
    cat_idx = [FEATURES.index(c) for c in CAT]

    if reg.score_only():
        print('1) RESPONSE-МОДЕЛЬ — SCORE_ONLY: загружаю сохранённую модель bonus (без обучения)')
        final = reg.load('bonus', CatBoostClassifier)
    else:
        print('1) RESPONSE-МОДЕЛЬ (какой бонус рекомендовать)')
        df = client.query_df(TRAIN_SQL)
        print(f'   игроков с бонусом: {len(df)}')
        df = df[df['bonus_type'].isin(BONUS_TYPES)].copy()
        train = df[df['mat'] >= 30].sort_values('fb_date').reset_index(drop=True)
        for c in CAT:
            train[c] = train[c].astype(str)
        print(f'   обучающих (mat>=30, известные типы): {len(train)}  ·  retention-30 база {train.retained.mean():.3f}')
        print('   распределение по типам бонуса:')
        for bt, n in train['bonus_type'].value_counts().items():
            print(f'     {bt:16s} {n:5d}  retention {train[train.bonus_type==bt].retained.mean():.3f}')

        split = int(len(train) * 0.8)
        tr, te = train.iloc[:split], train.iloc[split:]
        model = CatBoostClassifier(iterations=500, depth=5, learning_rate=0.05,
                                   loss_function='Logloss', eval_metric='AUC', random_seed=42, verbose=False)
        model.fit(Pool(tr[FEATURES], tr['retained'], cat_features=cat_idx),
                  eval_set=Pool(te[FEATURES], te['retained'], cat_features=cat_idx))
        auc = roc_auc_score(te['retained'], model.predict_proba(Pool(te[FEATURES], cat_features=cat_idx))[:, 1])
        print(f'   AUC (test по времени): {auc:.3f}')

        final = CatBoostClassifier(iterations=500, depth=5, learning_rate=0.05,
                                   loss_function='Logloss', random_seed=42, verbose=False)
        final.fit(Pool(train[FEATURES], train['retained'], cat_features=cat_idx))
        reg.save('bonus', final, features=FEATURES, cat_features=CAT,
                 metrics={'roc_auc': round(float(auc), 3)},
                 extra={'target': 'retained_30d_after_bonus', 'table': 'player_bonus_ml',
                        'bonus_types': BONUS_TYPES})

    print('\n   Скоринг: лучший бонус для каждого игрока...')
    sc = client.query_df(SCORE_SQL)
    base = sc.drop(columns=['casino_player_id'])
    for c in ['provider', 'country', 'affiliate_type']:
        base[c] = base[c].astype(str)
    preds = {}
    for bt in BONUS_TYPES:
        b = base.copy(); b['bonus_type'] = bt
        preds[bt] = final.predict_proba(Pool(b[FEATURES], cat_features=cat_idx))[:, 1]
    P = pd.DataFrame(preds)
    rec = sc[['casino_player_id']].copy()
    rec['rec_bonus'] = P.idxmax(axis=1)
    rec['rec_response'] = P.max(axis=1).round(4)
    rec['casino_player_id'] = rec['casino_player_id'].astype('uint32')
    rec['rec_response'] = rec['rec_response'].astype('float64')

    client.command('DROP TABLE IF EXISTS player_bonus_ml')
    client.command('CREATE TABLE player_bonus_ml (casino_player_id UInt32, rec_bonus String, rec_response Float64) '
                   'ENGINE = MergeTree ORDER BY casino_player_id')
    client.insert_df('player_bonus_ml', rec[['casino_player_id', 'rec_bonus', 'rec_response']])
    print(f'   ✅ рекомендации записаны в retention.player_bonus_ml: {len(rec)}')
    print('   что система рекомендует по базе:')
    for bt, n in rec['rec_bonus'].value_counts().items():
        print(f'     {bt:16s} {n:6d}')

    print('\n2) UPLIFT (квазиэксперимент, propensity-matching) — directional, контроль тонкий')
    u = quasi_uplift(client)
    print(f'   treated={u["n_treated"]}  control={u["n_control"]}')
    print(f'   retention-30:  бонус {u["retain_treated"]:.3f}  vs  без бонуса {u["retain_control"]:.3f}')
    print(f'   ATT (matched): {u["att"]*100:+.1f} п.п.   95% CI [{u["ci_lo"]*100:+.1f}; {u["ci_hi"]*100:+.1f}]')
    print('   ⚠️ наблюдательная оценка (не RCT): контроль из небонусных депозиторов мал и может быть смещён.')

    # сохраним uplift-сводку для дашборда
    client.command('DROP TABLE IF EXISTS bonus_uplift')
    client.command('CREATE TABLE bonus_uplift (metric String, value Float64) ENGINE = TinyLog')
    client.insert('bonus_uplift', [
        ['n_treated', u['n_treated']], ['n_control', u['n_control']],
        ['retain_treated', round(u['retain_treated'], 4)], ['retain_control', round(u['retain_control'], 4)],
        ['att_pp', round(u['att'] * 100, 2)], ['ci_lo_pp', round(u['ci_lo'] * 100, 2)], ['ci_hi_pp', round(u['ci_hi'] * 100, 2)],
    ], column_names=['metric', 'value'])
    print('   ✅ uplift-сводка -> retention.bonus_uplift')


if __name__ == '__main__':
    main()
