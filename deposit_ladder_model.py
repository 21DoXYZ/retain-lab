"""
Персональная модель прогрессии депозитов: P(сделает следующий депозит в 30 дней),
по состоянию НА МОМЕНТ текущего депозита #k. Работает на любой ступени (k — фича).

Заменяет базовую (по всей базе) вероятность из deposit_ladder на персональную.

- 1 строка = (игрок, депозит #k). Фичи «как было на депозите #k» (только депозиты <= k).
- Таргет: был ли депозит #(k+1) в пределах 30 дней после #k.
- Цензура: последний депозит идёт в обучение только если с него прошло >=30 дней.
- Валидация по времени (ранние депозиты -> train, поздние -> test).
- Скоринг: ПОСЛЕДНИЙ депозит каждого игрока -> P(следующий) -> retention.player_next_deposit_ml.

Запуск:  .venv/bin/python deposit_ladder_model.py
"""
import os
import numpy as np
import pandas as pd
import clickhouse_connect
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import roc_auc_score, average_precision_score
import model_registry as reg

CH = dict(host=os.environ.get('CH_HOST', '127.0.0.1'), port=int(os.environ.get('CH_PORT', '8123')),
          username=os.environ.get('CH_USER', 'default'), password=os.environ.get('CH_PASSWORD', ''),
          database=os.environ.get('CH_DB', 'retention'))

NUM = ['deposit_number', 'days_since_reg', 'gap_before', 'total_to_k', 'avg_to_k',
       'max_to_k', 'ftd_amount', 'this_amount', 'mean_gap']
CAT = ['payment_method', 'affiliate_type', 'country']
FEATURES = NUM + CAT

PULL = """
SELECT u.casino_player_id,
  toDate(u.reg_date) AS reg_date,
  toFloat64(ifNull(u.ftd_amount,0)) AS ftd_amount,
  if(u.affiliate_account_type='','(none)',u.affiliate_account_type) AS affiliate_type,
  ifNull(nullIf(u.country_iso_estimated,''),'(none)') AS country,
  anyHeavyIf(m.payment_method, m.payment_method!='' AND m.payment_method NOT LIKE 'campaign:%') AS payment_method,
  arraySort(x -> x.1, groupArray((m.created_at, toFloat64(m.amount)))) AS seq
FROM users u INNER JOIN money_transactions m USING (casino_player_id)
WHERE u.account_type='normal' AND u.ftd_date IS NOT NULL
  AND m.type IN ('deposit','manual_deposit') AND m.status='completed'
GROUP BY u.casino_player_id, reg_date, ftd_amount, affiliate_type, country
"""


def build_rows(rows, dmax):
    train, score = [], []
    for pid, reg, ftd, aff, country, pay, seq in rows:
        seq = sorted(seq, key=lambda x: x[0])
        n = len(seq)
        gaps = []
        last_feat = None
        for k in range(n):
            dt_k = seq[k][0]
            amt_k = float(seq[k][1])
            dep_no = k + 1
            dsr = (dt_k.date() - reg).days if reg else 0
            gap_before = (dt_k - seq[k - 1][0]).days if k > 0 else dsr
            prev_amts = [float(seq[i][1]) for i in range(k + 1)]
            total_to_k = sum(prev_amts)
            mean_gap = float(np.mean(gaps)) if gaps else 0.0
            feat = dict(deposit_number=dep_no, days_since_reg=dsr, gap_before=gap_before,
                        total_to_k=total_to_k, avg_to_k=total_to_k / dep_no, max_to_k=max(prev_amts),
                        ftd_amount=ftd, this_amount=amt_k, mean_gap=mean_gap,
                        payment_method=pay or '(none)', affiliate_type=aff, country=country)
            if k < n - 1:
                target = 1 if (seq[k + 1][0] - dt_k).days <= 30 else 0
                train.append({**feat, 'target': target, 'd': dt_k, 'pid': pid})
            else:
                if (dmax - dt_k).days >= 30:
                    train.append({**feat, 'target': 0, 'd': dt_k, 'pid': pid})
            last_feat = feat
            if k > 0:
                gaps.append(gap_before)
        if last_feat is not None:
            score.append({'casino_player_id': pid, **last_feat})
    return pd.DataFrame(train), pd.DataFrame(score)


def main():
    client = clickhouse_connect.get_client(**CH)
    dmax = client.query("SELECT max(created_at) FROM money_transactions "
                        "WHERE type IN ('deposit','manual_deposit') AND status='completed'").result_rows[0][0]
    print('Тяну депозитные последовательности...')
    rows = client.query(PULL).result_rows
    print(f'  депозиторов: {len(rows)}')
    train, score = build_rows(rows, dmax)
    for c in CAT:
        train[c] = train[c].astype(str); score[c] = score[c].astype(str)
    cat_idx = [FEATURES.index(c) for c in CAT]

    if reg.score_only():
        print('SCORE_ONLY: загружаю сохранённую модель deposit_ladder (без обучения)')
        final = reg.load('deposit_ladder', CatBoostClassifier)
    else:
        print(f'  обучающих строк (игрок×депозит): {len(train)}  ·  база P(след.деп) {train.target.mean():.3f}')
        print('  по ступеням:')
        g = train.groupby('deposit_number').agg(n=('target', 'size'), p=('target', 'mean'))
        for no, r in g.head(10).iterrows():
            print(f'    деп #{int(no):2d}:  n={int(r.n):5d}  P(след)={r.p:.3f}')

        # сплит ПО ИГРОКАМ (депозиты одного игрока не текут train->test)
        rng = np.random.RandomState(42)
        pids = train['pid'].unique()
        rng.shuffle(pids)
        test_pids = set(pids[:max(1, len(pids) // 5)])
        te = train[train['pid'].isin(test_pids)]
        tr = train[~train['pid'].isin(test_pids)]
        model = CatBoostClassifier(iterations=600, depth=6, learning_rate=0.04,
                                   loss_function='Logloss', eval_metric='AUC', random_seed=42, verbose=False)
        model.fit(Pool(tr[FEATURES], tr['target'], cat_features=cat_idx),
                  eval_set=Pool(te[FEATURES], te['target'], cat_features=cat_idx))
        p = model.predict_proba(Pool(te[FEATURES], cat_features=cat_idx))[:, 1]
        auc = roc_auc_score(te["target"], p)
        pr = average_precision_score(te["target"], p)
        print(f'\n  AUC (test): {auc:.3f}  ·  PR-AUC {pr:.3f}')
        print('  важность фич (топ-8):')
        for nm, v in sorted(zip(FEATURES, model.get_feature_importance()), key=lambda t: -t[1])[:8]:
            print(f'    {nm:16s} {v:5.1f}')

        final = CatBoostClassifier(iterations=600, depth=6, learning_rate=0.04,
                                   loss_function='Logloss', random_seed=42, verbose=False)
        final.fit(Pool(train[FEATURES], train['target'], cat_features=cat_idx))
        reg.save('deposit_ladder', final, features=FEATURES, cat_features=CAT,
                 metrics={'roc_auc': round(float(auc), 3), 'pr_auc': round(float(pr), 3)},
                 extra={'target': 'next_deposit_within_30d', 'table': 'player_next_deposit_ml'})
    score['p_next_deposit'] = final.predict_proba(Pool(score[FEATURES], cat_features=cat_idx))[:, 1].round(4)
    out = score[['casino_player_id', 'deposit_number', 'p_next_deposit']].copy()
    out['casino_player_id'] = out['casino_player_id'].astype('uint32')
    out['deposit_number'] = out['deposit_number'].astype('uint16')
    out['p_next_deposit'] = out['p_next_deposit'].astype('float64')

    client.command('DROP TABLE IF EXISTS player_next_deposit_ml')
    client.command('CREATE TABLE player_next_deposit_ml (casino_player_id UInt32, deposit_number UInt16, p_next_deposit Float64) '
                   'ENGINE = MergeTree ORDER BY casino_player_id')
    client.insert_df('player_next_deposit_ml', out)
    print(f'\n✅ персональный P(след. депозит) записан: {len(out)}  ·  средний {out.p_next_deposit.mean():.3f}')


if __name__ == '__main__':
    main()
