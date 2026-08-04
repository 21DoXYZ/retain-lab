> For the complete documentation index, see [llms.txt](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/vip-intelligence/data-aggregation-guide.md).

# Data Aggregation Guide

## Overview

VIP Intelligence API supports both transaction-level and pre-aggregated data uploads. This guide explains when and how to use aggregated endpoints for optimal performance.

{% hint style="warning" %}
&#x20;**Recommendation: Use transaction-level uploads whenever possible.**

Pre-aggregated data reduces model accuracy because aggregation inevitably loses granular behavioral signals that our models rely on. Use aggregated endpoints only if your infrastructure cannot support transaction-level uploads or the volume makes individual transactions impractical.
{% endhint %}

## When to Use Aggregation

**Prefer transaction-level endpoints** (`/v1/data/bets`) in all cases where possible. Aggregated data degrades model performance.

**Use aggregated endpoints only when:**

* High transaction volume makes individual uploads impractical
* Your ETL pipeline cannot output raw transactions
* Network or infrastructure constraints require batching at the source

**Do not use aggregated endpoints** simply for convenience or because your team already aggregates data for internal analytics — in these cases, the raw transaction data is still available and should be used.

## Supported Aggregated Endpoints

| Endpoint                   | Transaction Endpoint | Description                         |
| -------------------------- | -------------------- | ----------------------------------- |
| `POST /v1/data/bets-daily` | `POST /v1/data/bets` | Daily aggregated betting statistics |

{% hint style="warning" %}
Balance data (`POST /v1/data/balances`) is also submitted with daily granularity, but it is **not an aggregated endpoint**.

Unlike bets and payments which aggregate multiple transactions, balance represents a **snapshot** of user's account balance at a specific point in time each day.
{% endhint %}

### Bets Aggregation

#### Endpoint

```
POST /v1/data/bets-daily
```

#### Grouping Dimensions

Aggregate your transaction-level bets by this unique combination:

* `date` (daily granularity, YYYY-MM-DD format)
* `user_id`
* `device_type`
* `game_id`
* `game_name`
* `provider_id`
* `provider_name`
* `currency`
* `country`
* `bet_type`
* `aggregator`
* `status`
* `is_real_money`

#### Aggregated Metrics

For each unique combination above, calculate:

* `bet_sum` — total of all bet amounts
* `bet_count` — number of bets
* `win_sum` — total of all win amounts (can be NULL if no wins)
* `win_count` — number of bets with win\_amount > 0 (can be NULL)

#### Implementation Examples

**SQL (PostgreSQL/MySQL):**

```sql
SELECT 
  DATE(event_dt) AS date,
  user_id,
  device_type,
  game_id,
  game_name,
  provider_id,
  provider_name,
  currency,
  country,
  bet_type,
  aggregator,
  status,
  is_real_money,
  SUM(bet_amount) AS bet_sum,
  COUNT(*) AS bet_count,
  SUM(win_amount) AS win_sum,
  SUM(CASE WHEN win_amount > 0 THEN 1 ELSE 0 END) AS win_count
FROM bets
WHERE DATE(event_dt) = '2024-02-01'
GROUP BY date, user_id, device_type, game_id, game_name, provider_id, provider_name,
         currency, country, bet_type, aggregator, status, is_real_money;
```

**Python (Pandas):**

```python
daily_bets = df.groupby([
    'date', 'user_id', 'device_type', 'game_id', 'game_name',
    'provider_id', 'provider_name', 'currency', 'country', 
    'bet_type', 'aggregator', 'status', 'is_real_money'
]).agg(
    bet_sum=('bet_amount', 'sum'),
    bet_count=('bet_amount', 'count'),
    win_sum=('win_amount', 'sum'),
    win_count=('win_amount', lambda x: (x > 0).sum())
).reset_index()
```

#### Example Request

```json
{
  "items": [
    {
      "date": "2024-02-01",
      "user_id": "12345",
      "device_type": "mobile",
      "game_id": "game_001",
      "game_name": "Super Fun Game",
      "provider_id": "provider_001",
      "provider_name": "Provider Inc.",
      "currency": "USD",
      "country": "US",
      "bet_type": "casino",
      "aggregator": "aggregator_001",
      "status": "success",
      "is_real_money": true,
      "bet_sum": 250.00,
      "bet_count": 5,
      "win_sum": 180.00,
      "win_count": 2
    }
  ]
}
```

## Best Practices

### Data Quality

* **Completeness** — Ensure all grouping dimensions are populated (use NULL for optional fields if no value)
* **Consistency** — Use the same date format (YYYY-MM-DD) across all records
* **Accuracy** — Verify aggregated sums match original transaction totals

### Timing Consistency

* **Consistency** — Capture balance at the same time each day (e.g. 00:00 UTC, 23:59 UTC, or end of business day)
* **Recommended** — End-of-day balance (23:59 UTC) provides the most complete picture of daily activity

### Performance

* **Batch size** — Send up to 1000 records per request for optimal performance
* **Parallel uploads** — You can send multiple batches in parallel for different date ranges
* **Scheduling** — Aggregate and upload daily data during off-peak hours

### Error Handling

* **Validation** — API validates that aggregated metrics are non-negative
* **Duplicates** — Sending the same aggregated record twice will overwrite the previous value
* **Partial failures** — If some records fail validation, successful records are still processed

### Migration Strategy

If you're currently using transaction-level endpoints and want to switch to aggregated:

1. **Test in parallel** — Send both transaction-level and aggregated data to dev environment
2. **Verify consistency** — Compare prediction results from both approaches
3. **Gradual rollout** — Start with one data type (e.g., bets) before migrating others
4. **Monitor performance** — Track API response times and error rates

## FAQ

**Q: Can I mix transaction-level and aggregated data?**\
A: Technically yes, the API will accept both. However, it's pointless — during model training, we'll use only one data format (either transaction-level or aggregated). Mixing formats won't provide any benefit and may create confusion.

**Q: What happens if I aggregate by different dimensions?**\
A: The API will accept any valid aggregated data structure. However, for optimal model performance, we recommend following the grouping dimensions specified in this guide. If you need to aggregate differently, contact your account manager to discuss your use case.

**Q: How do I handle timezone differences?**\
A: Use any consistent timezone across your data. Our models recalculate daily aggregates during training regardless of the timezone you use. The important thing is consistency — don't mix timezones within the same dataset.

**Q: Can I re-upload data for the same date?**\
A: Yes, you can re-upload data for any date. The system automatically deduplicates records before model training, so the latest uploaded data will be used.
