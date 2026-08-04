> For the complete documentation index, see [llms.txt](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/game-recommender/similar-games.md).

# Similar games

## Base URL

**Production Environment**

```
https://api.mico.team
```

**Development Environment**

```
https://api.dev.mico.team
```

**Similar Games** is an ML model that returns a list of games similar to the requested one. No personal player data is used — all logic is based on aggregated behavioral connections between games.

***

### How It Works

Similar Games is a **B2B product for game aggregators** — platforms that sit between game providers and casino operators, distributing a shared game catalog across many casinos.

The aggregator integrates once: sends betting data to MICo daily, and gets game similarity recommendations via API. How the aggregator surfaces these recommendations to end users is up to them.

**How the model works:** it analyzes betting history across the aggregator's entire network — counting how often each pair of games was played by the same player. Games that frequently appear together in player histories are considered similar. This builds a game-to-game similarity graph that reflects real player behavior, not just genre labels or provider metadata.

Because the model trains on data from all operators in the network — not just one — it has significantly richer statistics, especially for long-tail games that would have too little data at a single operator level.

Recommendations are recalculated daily in batch, served synchronously, and are available for any game that had at least one bet in the last 14 days.

***

## Authentication

All API requests require authentication using a Bearer token in the `Authorization` header:

```shellscript
Authorization: Bearer YOUR_API_TOKEN
```

Contact your account manager to receive your API credentials.

## Get Access Token

> Authenticate using OAuth 2.0 client credentials to receive an access token. \
> \
> \*\*Important:\*\* You must specify the \`scope\` parameter with the permissions required for your operations. The scopes must match your product subscription (VIP Intelligence, Game Recommender, or both).\
> \
> Use this token in the Authorization header (\`Bearer {token}\`) for all subsequent API requests.\
> \
> See the \[OAuth Scopes documentation]\(#) for the complete list of available scopes and their usage.<br>

```json
{"openapi":"3.1.0","info":{"title":"Authentication Component","version":"1.0.0"},"servers":[{"url":"https://api.mico.team","description":"Production"},{"url":"https://api.dev.mico.team","description":"Development"}],"paths":{"/auth/token":{"post":{"tags":["Authentication"],"summary":"Get Access Token","description":"Authenticate using OAuth 2.0 client credentials to receive an access token. \n\n**Important:** You must specify the `scope` parameter with the permissions required for your operations. The scopes must match your product subscription (VIP Intelligence, Game Recommender, or both).\n\nUse this token in the Authorization header (`Bearer {token}`) for all subsequent API requests.\n\nSee the [OAuth Scopes documentation](#) for the complete list of available scopes and their usage.\n","operationId":"auth_token_post","requestBody":{"required":true,"content":{"application/x-www-form-urlencoded":{"schema":{"$ref":"#/components/schemas/AuthRequest"}}}},"responses":{"200":{"description":"Successfully authenticated","content":{"application/json":{"schema":{"$ref":"#/components/schemas/AuthResponse"}}}},"401":{"description":"Invalid credentials","content":{"application/json":{"schema":{"$ref":"#/components/schemas/AuthError"}}}}}}}},"components":{"schemas":{"AuthRequest":{"type":"object","required":["client_id","client_secret","grant_type"],"properties":{"grant_type":{"type":"string","enum":["client_credentials"],"description":"OAuth 2.0 grant type. Must be client_credentials"},"client_id":{"type":"string","description":"Your client ID provided during onboarding"},"client_secret":{"type":"string","description":"Your client secret provided during onboarding"},"scope":{"type":"string","description":"Space-separated list of OAuth scopes you want to request. Must match your product subscription. See OAuth Scopes documentation for available scopes."}}},"AuthResponse":{"type":"object","required":["access_token","token_type","expires_in"],"properties":{"access_token":{"type":"string","description":"JWT access token for Authorization header"},"token_type":{"type":"string","description":"Token type, always Bearer"},"scope":{"type":"string","description":"Access scopes granted (may be empty)"},"expires_in":{"type":"integer","description":"Token expiration time in seconds (typically 86400 for 24 hours)"},"id_token":{"type":"string","description":"ID token for user identification (not used in API requests)"}}},"AuthError":{"type":"object","properties":{"error":{"type":"string","description":"Error code"},"error_description":{"type":"string","description":"Human-readable error description"}}}}}}
```

***

## Data Upload

Betting data can be delivered in two ways — choose based on your infrastructure:

<table><thead><tr><th width="133.811767578125">Method</th><th>Format</th><th>When to use</th></tr></thead><tbody><tr><td><strong>S3 MICo</strong></td><td>Parquet files</td><td>You have a data pipeline, large volumes, batch delivery</td></tr><tr><td><strong>API</strong></td><td>JSON, batches up to 1000 records</td><td>No S3 integration, easier to send directly from your application</td></tr></tbody></table>

Use **one** method only — not both simultaneously.

***

## Upload Bet Transactions

> Upload individual bet transaction data. Use this endpoint when you have detailed transaction-level betting data.

```json
{"openapi":"3.1.0","info":{"title":"MICo Data Upload API","version":"1.0.0"},"servers":[{"url":"https://api.mico.team","description":"Production"},{"url":"https://api.dev.mico.team","description":"Development"}],"security":[{"bearerAuth":[]}],"components":{"securitySchemes":{"bearerAuth":{"type":"http","scheme":"bearer","bearerFormat":"JWT"}},"schemas":{"BetBatchRequest":{"properties":{"items":{"items":{"$ref":"#/components/schemas/BetRequest"},"type":"array","maxItems":1000,"minItems":1,"title":"Items","description":"List of dataset records"}},"type":"object","required":["items"],"title":"BetBatchRequest","description":"Model for batch bet data in API requests."},"BetRequest":{"properties":{"bet_id":{"type":"string","minLength":1,"title":"Bet Id","description":"Unique bet identifier"},"user_id":{"type":"string","minLength":1,"title":"User Id","description":"Unique user identifier"},"device_type":{"type":"string","enum":["mobile","desktop","other","undefined"],"title":"Device Type","description":"Type of device used"},"game_id":{"type":"string","minLength":1,"title":"Game Id","description":"Unique game identifier"},"game_name":{"type":"string","maxLength":200,"minLength":1,"title":"Game Name","description":"Name of the game"},"bet_amount":{"type":"number","minimum":0,"title":"Bet Amount","description":"Amount of the bet placed"},"win_amount":{"anyOf":[{"type":"number","minimum":0},{"type":"null"}],"title":"Win Amount","description":"Amount won from the bet"},"currency":{"type":"string","minLength":2,"title":"Currency","description":"Currency"},"country":{"anyOf":[{"type":"string","maxLength":100,"minLength":2},{"type":"null"}],"title":"Country","description":"Country name"},"provider_id":{"type":"string","minLength":1,"title":"Provider Id","description":"Unique provider identifier"},"provider_name":{"type":"string","maxLength":200,"minLength":1,"title":"Provider Name","description":"Name of the provider"},"status":{"anyOf":[{"type":"string","enum":["success","cancelled","pending"]},{"type":"null"}],"title":"Status","description":"Status of the bet"},"aggregator":{"anyOf":[{"type":"string","maxLength":200,"minLength":1},{"type":"null"}],"title":"Aggregator","description":"Game aggregator"},"session_id":{"anyOf":[{"type":"string","minLength":1},{"type":"null"}],"title":"Session Id","description":"Session identifier"},"bet_type":{"anyOf":[{"type":"string","maxLength":100,"minLength":1},{"type":"null"}],"title":"Bet Type","description":"Type of bet"},"is_test_user":{"anyOf":[{"type":"boolean"},{"type":"null"}],"title":"Is Test User","description":"Indicates if the user is a test user"},"is_real_money":{"anyOf":[{"type":"boolean"},{"type":"null"}],"title":"Is Real Money","description":"Indicates if the bet is placed with real money"},"event_dt":{"type":"string","format":"date-time","title":"Event Dt","description":"Timestamp of when the bet was placed"},"commission_amount":{"anyOf":[{"type":"number","minimum":0},{"type":"null"}],"title":"Commission Amount","description":"Commission amount for the bet"}},"type":"object","required":["bet_id","user_id","device_type","game_id","game_name","bet_amount","currency","provider_id","provider_name","event_dt"],"title":"BetRequest","description":"Model for bet data in API requests."},"HTTPValidationError":{"properties":{"detail":{"items":{"$ref":"#/components/schemas/ValidationError"},"type":"array","title":"Detail"}},"type":"object","title":"HTTPValidationError"},"ValidationError":{"properties":{"loc":{"items":{"anyOf":[{"type":"string"},{"type":"integer"}]},"type":"array","title":"Location"},"msg":{"type":"string","title":"Message"},"type":{"type":"string","title":"Error Type"},"input":{"title":"Input"},"ctx":{"type":"object","title":"Context"}},"type":"object","required":["loc","msg","type"],"title":"ValidationError"}}},"paths":{"/v1/data/bets":{"post":{"tags":["Data Upload"],"summary":"Upload Bet Transactions","description":"Upload individual bet transaction data. Use this endpoint when you have detailed transaction-level betting data.","operationId":"endpoint_api_v1_bets_post","parameters":[],"requestBody":{"required":true,"content":{"application/json":{"schema":{"$ref":"#/components/schemas/BetBatchRequest"}}}},"responses":{"202":{"description":"Successful Response","content":{"application/json":{"schema":{}}}},"422":{"description":"Validation Error","content":{"application/json":{"schema":{"$ref":"#/components/schemas/HTTPValidationError"}}}}}}}}}
```

***

## Get Recommendations

## Get Similar Recommendations

> Returns game recommendations similar to the specified game, based on gameplay characteristics

```json
{"openapi":"3.1.0","info":{"title":"MICo Recommender Service API","version":"1.0.0"},"servers":[{"url":"https://api.mico.team","description":"Production"},{"url":"https://api.dev.mico.team","description":"Development"},{"url":"https://edge.mico.team","description":"Production (Edge) — available without IP whitelisting"},{"url":"https://edge.dev.mico.team","description":"Development (Edge) — available without IP whitelisting"}],"security":[{"bearerAuth":[]}],"components":{"securitySchemes":{"bearerAuth":{"type":"http","scheme":"bearer","description":"Bearer token authentication. Obtain token via POST /auth/token"}},"schemas":{"GameRecommendationsRequest":{"properties":{"limit":{"type":"integer","maximum":100,"minimum":1,"title":"Limit","description":"Number of recommendations to return (max 100)"},"offset":{"type":"integer","minimum":0,"title":"Offset","description":"Pagination offset for retrieving additional recommendations"},"game_id":{"type":"string","title":"Game Id","description":"Game Identifier"}},"type":"object","required":["limit","offset","game_id"],"title":"GameRecommendationsRequest"},"RecommendationsResponse":{"properties":{"game_ids":{"items":{"type":"string"},"type":"array","title":"Game Ids","description":"List of recommended game IDs, ordered by relevance (highest relevance first)"}},"type":"object","required":["game_ids"],"title":"RecommendationsResponse"},"HTTPValidationError":{"properties":{"detail":{"items":{"$ref":"#/components/schemas/ValidationError"},"type":"array","title":"Detail"}},"type":"object","title":"HTTPValidationError"},"ValidationError":{"properties":{"loc":{"items":{"anyOf":[{"type":"string"},{"type":"integer"}]},"type":"array","title":"Location"},"msg":{"type":"string","title":"Message"},"type":{"type":"string","title":"Error Type"},"input":{"title":"Input"},"ctx":{"type":"object","title":"Context"}},"type":"object","required":["loc","msg","type"],"title":"ValidationError"}}},"paths":{"/v1/recommendations/similar_games":{"post":{"tags":["Recommendations"],"summary":"Get Similar Recommendations","description":"Returns game recommendations similar to the specified game, based on gameplay characteristics","operationId":"similar_games_recommendations_v1_recommendations_similar_games_post","requestBody":{"required":true,"content":{"application/json":{"schema":{"$ref":"#/components/schemas/GameRecommendationsRequest"}}}},"responses":{"200":{"description":"Successful Response","content":{"application/json":{"schema":{"$ref":"#/components/schemas/RecommendationsResponse"}}}},"422":{"description":"Validation Error","content":{"application/json":{"schema":{"$ref":"#/components/schemas/HTTPValidationError"}}}}}}}}}
```

***

### Typical Integration Flow

1. **Authenticate**
   * Get access token: `POST /auth/token`
   * Use the token in `Authorization` header for all requests
2. **Upload Betting Data**
   * Send betting transactions: `POST /v1/data/bets`
   * Upload in batches (max 1000 records)
   * Use cron jobs for continuous data upload
3. **Get Recommendations**
   * Request recommendations: `POST /v1/recommendations/similar_games`
   * Cache results 5–15 minutes on client side
   * Use pagination for large result sets
4. **Ongoing Updates**
   * Continue uploading new betting data daily
   * Fetch fresh recommendations as needed

***

### Error Codes

The API uses standard HTTP status codes:

| Code | Description               |
| ---- | ------------------------- |
| 200  | Success (recommendations) |
| 202  | Accepted (data upload)    |
| 400  | Bad Request               |
| 401  | Unauthorized              |
| 422  | Validation Error          |
| 429  | Rate Limit                |
| 500  | Server Error              |

***

### Rate Limits

* Data Upload: 100 requests/second
* Recommendations: 100 requests/second
* Batch Size: Maximum 1000 records per upload request
