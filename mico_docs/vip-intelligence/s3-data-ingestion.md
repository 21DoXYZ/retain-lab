> For the complete documentation index, see [llms.txt](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/vip-intelligence/s3-data-ingestion.md).

# S3 Data Ingestion

{% hint style="info" %}
MICo supports two methods of data ingestion: via REST API and via S3. This section describes the S3 ingestion method. If you have the option to use the API — we recommend it.
{% endhint %}

## File Format

| Parameter   | Value                                             |
| ----------- | ------------------------------------------------- |
| Format      | Apache Parquet                                    |
| Compression | Snappy (default) or GZIP                          |
| File size   | Recommended 128–512 MB per file for large volumes |

***

## Access and Authentication

Static AWS S3 credentials are used for file uploads. They are **different** from the API token used for the REST API.

MICo provides two environments:

| Parameter         | Development                             | Production                              |
| ----------------- | --------------------------------------- | --------------------------------------- |
| Bucket Name       | `mico-dev-data-exchange`                | `mico-prod-data-exchange`               |
| Region            | `eu-central-1`                          | `eu-central-1`                          |
| Endpoint URL      | `https://s3.eu-central-1.amazonaws.com` | `https://s3.eu-central-1.amazonaws.com` |
| Access Key ID     | Provided by MICo team                   | Provided by MICo team                   |
| Secret Access Key | Provided by MICo team                   | Provided by MICo team                   |
| `client_id`       | Provided by MICo team                   | Provided by MICo team                   |

Dev is used during the pilot phase to set up the integration and verify data correctness. Once verified, the switch to Prod is made.

`client_id` — a unique client identifier used as the path identifier in S3.

{% hint style="warning" %}
**Important:** do not use the API token to connect to S3. This is a separate authentication mechanism.
{% endhint %}

{% hint style="warning" %}
**Critical for connection setup:** for security reasons, the global `ListAllMyBuckets` permission is disabled for your account. To avoid an *Access Denied* or *NoSuchBucket* error, the path `projects/<client_id>/input/` must be explicitly set in your connection settings. The folder will be created automatically when the first file is uploaded.️&#x20;
{% endhint %}

***

## Directory Structure

Files must be placed strictly according to the path structure below. Files placed outside this structure will be **ignored**.

### Path Template

{% code overflow="wrap" %}

```
s3://<bucket>/projects/<client_id>/input/<table_name>__<ingest_type>/load_dt=<YYYY-MM-DD>/<filename>.parquet
```

{% endcode %}

### Rules

* `<client_id>` — unique identifier provided by the MICo team
* `<table_name>` — allowed values are described below
* `<ingest_type>` — required suffix separated by a double underscore, defines the ingestion mode:
  * `append` — incremental load. Each partition contains only new data for the given date (events, transactions)
  * `reload` — full reload. Each partition contains a complete current snapshot of the table (directories, profiles)
  * `update` — upsert. Records are added, existing records are updated
* `load_dt=<YYYY-MM-DD>` — data export date (UTC)
* `<filename>` — any unique file name&#x20;

### Example

{% code overflow="wrap" %}

```
s3://mico-prod-data-exchange/projects/your_client_id/input/bets__append/load_dt=2025-07-23/part_0001.parquet
```

{% endcode %}

***

### Onboarding Process (Dev → Prod)

1. **Dev — technical verification:** obtain Dev credentials from the MICo team, upload a test dataset, and verify that files are received, path structure is correct, and table schemas pass validation. Data completeness is not critical at this stage.
2. **Joint review:** the MICo team confirms that data is read correctly and the structure meets requirements.
3. **Switch to Prod:** obtain Prod credentials, perform a full historical data load and set up regular incremental ingestion. The model is trained on data from Prod.

***

### ETL: Best Practices

#### Idempotent Writes

The system supports re-uploading data for any date. If an error is found in data for a past date:

1. Generate a corrected Parquet file.
2. Upload it under a **new date** in the partition `load_dt=<YYYY-MM-DD>`.

Before training, the system scans all partitions and takes the latest state of each record.

{% hint style="info" %}
**File deletion from S3 is not available** — the provided credentials grant read and write permissions only. This is intentional to prevent accidental deletion of data used for model training. If you need to remove incorrect or unnecessary files, please contact the MICo team.
{% endhint %}

#### Rolling Window

To ensure data integrity, it is recommended to upload data with overlap:

* **Optimal:** every night, upload data for the last several days. This automatically corrects transactions that may have missed the previous upload.
* **Minimum:** data for the past 24 hours only (strict Append Only).

## Supported Datasets

<table><thead><tr><th width="183.4765625">Dataset</th><th>Ingest Type</th><th>Description</th></tr></thead><tbody><tr><td><code>bets</code></td><td><code>__append</code></td><td>Raw bet log, incremental by date</td></tr><tr><td><code>payments</code></td><td><code>__append</code></td><td>Deposit and withdrawal transactions, incremental</td></tr><tr><td><code>balances-daily</code></td><td><code>__append</code></td><td>Balance snapshots, incremental</td></tr><tr><td><code>users</code></td><td><code>__reload</code></td><td>Full snapshot of player profiles</td></tr><tr><td><code>vip-users</code></td><td><code>__append</code> / <code>__reload</code> / <code>__update</code></td><td>VIP status history. Partner chooses the type but must specify it</td></tr></tbody></table>

***

## Dataset Schemas

All fields in the Parquet file must match the specified types. Extra fields are ignored. Missing required fields will result in a validation error.

#### bets

Raw log of gaming activity (spins, sports bets). The highest-volume dataset.

<table><thead><tr><th width="155.7578125">Field</th><th width="115.419189453125">Type</th><th width="117.9140625">Required</th><th>Description</th></tr></thead><tbody><tr><td><code>bet_id</code></td><td>String</td><td>✅</td><td>Unique bet identifier</td></tr><tr><td><code>user_id</code></td><td>String</td><td>✅</td><td>Player ID</td></tr><tr><td><code>event_dt</code></td><td>Datetime</td><td>✅</td><td>Date and time of the bet</td></tr><tr><td><code>bet_amount</code></td><td>Float</td><td>✅</td><td>Bet amount</td></tr><tr><td><code>currency</code></td><td>String</td><td>✅</td><td>ISO 4217 currency code, e.g. <code>USD</code></td></tr><tr><td><code>game_id</code></td><td>String</td><td>✅</td><td>Unique game ID</td></tr><tr><td><code>game_name</code></td><td>String</td><td>✅</td><td>Game name</td></tr><tr><td><code>provider_id</code></td><td>String</td><td>✅</td><td>Provider ID</td></tr><tr><td><code>provider_name</code></td><td>String</td><td>✅</td><td>Provider name</td></tr><tr><td><code>device_type</code></td><td>String</td><td>✅</td><td>Device type. Allowed values: <code>mobile</code>, <code>desktop</code>, <code>other</code>, <code>undefined</code></td></tr><tr><td><code>win_amount</code></td><td>Float</td><td>—</td><td>Win amount</td></tr><tr><td><code>bet_type</code></td><td>String</td><td>—</td><td>Bet type (<code>casino</code>, <code>sport</code>, etc)</td></tr><tr><td><code>is_real_money</code></td><td>Boolean</td><td>—</td><td><code>true</code> if the bet was placed with real money (not bonus)</td></tr><tr><td><code>is_test_user</code></td><td>Boolean</td><td>—</td><td><code>true</code> if the user is a test account</td></tr><tr><td><code>status</code></td><td>String</td><td>—</td><td>Bet status. Allowed values: <code>success</code>, <code>pending</code>, <code>cancelled</code></td></tr><tr><td><code>aggregator</code></td><td>String</td><td>—</td><td>Game aggregator name</td></tr><tr><td><code>session_id</code></td><td>String</td><td>—</td><td>Game session ID</td></tr><tr><td><code>country</code></td><td>String</td><td>—</td><td>ISO 3166-1 country code, e.g. <code>US</code>, <code>GB</code></td></tr></tbody></table>

***

#### payments

Deposit and withdrawal transactions.

<table><thead><tr><th width="181.3671875">Field</th><th width="110.6146240234375">Type</th><th width="108.828125">Required</th><th>Description</th></tr></thead><tbody><tr><td><code>user_id</code></td><td>String</td><td>✅</td><td>Unique user identifier</td></tr><tr><td><code>payment_id</code></td><td>String</td><td>✅</td><td>Unique payment identifier</td></tr><tr><td><code>action</code></td><td>String</td><td>✅</td><td>Payment type. Allowed values: <code>deposit</code>, <code>withdrawal</code></td></tr><tr><td><code>amount</code></td><td>Float</td><td>✅</td><td>Payment amount</td></tr><tr><td><code>currency</code></td><td>String</td><td>✅</td><td>ISO 4217 currency code, e.g. <code>USD</code></td></tr><tr><td><code>status</code></td><td>String</td><td>✅</td><td>Payment status. Allowed values: <code>success</code>, <code>pending</code>, <code>failed</code>, <code>chargeback</code></td></tr><tr><td><code>event_dt</code></td><td>Datetime</td><td>✅</td><td>Date and time the payment was created</td></tr><tr><td><code>country</code></td><td>String</td><td>—</td><td>ISO 3166-1 country code, e.g. <code>US</code>, <code>GB</code></td></tr><tr><td><code>status_dt</code></td><td>Datetime</td><td>—</td><td>Date and time of the last status change</td></tr><tr><td><code>is_real_operation</code></td><td>Boolean</td><td>—</td><td><code>true</code> if the operation involved real money</td></tr><tr><td><code>payment_system</code></td><td>String</td><td>—</td><td>Payment system identifier</td></tr><tr><td><code>device_type</code></td><td>String</td><td>—</td><td>Device type. Allowed values: <code>mobile</code>, <code>desktop</code>, <code>other</code>, <code>undefined</code></td></tr><tr><td><code>wallet</code></td><td>String</td><td>—</td><td>Player's wallet identifier</td></tr></tbody></table>

***

#### balances-daily

Player balance snapshots. It is recommended to export the end-of-day state (23:59 UTC) for all active players.

<table><thead><tr><th width="135.1640625">Field</th><th width="115.55987548828125">Type</th><th width="115.3228759765625">Required</th><th>Description</th></tr></thead><tbody><tr><td><code>user_id</code></td><td>String</td><td>✅</td><td>Player ID</td></tr><tr><td><code>amount</code></td><td>Float</td><td>✅</td><td>Balance amount</td></tr><tr><td><code>currency</code></td><td>String</td><td>✅</td><td>ISO 4217 currency code, e.g. <code>USD</code></td></tr><tr><td><code>event_dt</code></td><td>Datetime</td><td>✅</td><td>Date and time the balance is valid for</td></tr></tbody></table>

***

#### users

Full snapshot of player profiles. Uploaded in full on every export (`__reload`).

<table><thead><tr><th width="182.2421875">Field</th><th width="125.703125">Type</th><th width="107.2603759765625">Required</th><th>Description</th></tr></thead><tbody><tr><td><code>user_id</code></td><td>String</td><td>✅</td><td>Player ID</td></tr><tr><td><code>registration_dt</code></td><td>Datetime</td><td>✅</td><td>Registration date and time</td></tr><tr><td><code>is_valid</code></td><td>Boolean</td><td>✅</td><td><code>true</code> if the user is valid (not a test account, etc.)</td></tr><tr><td><code>first_deposit_dt</code></td><td>Datetime</td><td>—</td><td>Date and time of the first deposit</td></tr><tr><td><code>date_of_birth</code></td><td>String</td><td>—</td><td>Date of birth. Format: <code>YYYY-MM-DD</code></td></tr><tr><td><code>country</code></td><td>String</td><td>—</td><td>ISO 3166-1 country code, e.g. <code>US</code>, <code>GB</code></td></tr><tr><td><code>affiliate_id</code></td><td>String</td><td>—</td><td>Affiliate identifier the player came from</td></tr></tbody></table>

***

#### vip-users

Player VIP level history. Used for training the `vip-churn` and `stable-vip` models.

<table><thead><tr><th width="221.9427490234375">Field</th><th width="113.4791259765625">Type</th><th width="106.796875">Required</th><th>Description</th></tr></thead><tbody><tr><td><code>user_id</code></td><td>String</td><td>✅</td><td>Player ID</td></tr><tr><td><code>segment_property_name</code></td><td>String</td><td>✅</td><td>VIP segment attribute name, e.g. <code>vip_level</code></td></tr><tr><td><code>segment_property_value</code></td><td>String</td><td>✅</td><td>Attribute value, e.g. <code>1</code>, <code>2</code>, <code>3</code> or <code>bronze</code>, <code>silver</code>, <code>gold</code></td></tr><tr><td><code>event_dt</code></td><td>Datetime</td><td>—</td><td>Date and time the value was assigned</td></tr></tbody></table>

***
