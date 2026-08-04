> For the complete documentation index, see [llms.txt](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/game-recommender/oauth-2.0-authentication-and-scopes.md).

# OAuth 2.0 Authentication & Scopes

## Overview

MICo Platform uses OAuth 2.0 for API authentication with a scope-based permission system. This ensures secure access control and follows the principle of least privilege—you only request the permissions you need for specific operations.

***

## Quick Start

#### 1. Get Your Credentials

During onboarding, you'll receive:

* `client_id` - Your unique client identifier
* `client_secret` - Your authentication secret (keep this secure!)

#### 2. Obtain an Access Token

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

**Example:** `game-recommender:data:write`

* **Product:** `game-recommender` (VIP Intelligence)
* **Resource:** `data` (data upload operations)
* **Action:** `write` (upload permission)

***

### Available Scopes

<table data-full-width="true"><thead><tr><th width="289.34765625">Scope</th><th width="192.02337646484375">Product</th><th width="627.07421875">Permission</th></tr></thead><tbody><tr><td><code>vip-intelligence:data:write</code></td><td>VIP Intelligence</td><td>Upload data for VIP Intelligence models</td></tr><tr><td><code>vip-intelligence:results:read</code></td><td>VIP Intelligence</td><td>Read VIP Intelligence predictions</td></tr><tr><td><code>game-recommender:data:write</code></td><td>Game Recommender</td><td>Upload data for Recommender models</td></tr><tr><td><code>game-recommender:results:read</code></td><td>Game Recommender</td><td>Read game recommendations</td></tr></tbody></table>

**Note:** You can only request scopes that match your product subscription.

***

## Common Scenarios

***

### Game Recommender Only

Request scopes: `game-recommender:data:write`, `game-recommender:results:read`

Available operations:

* Upload betting and user data
* Get game recommendations

### Both Products

Request scopes: `vip-intelligence:data:write`, `vip-intelligence:results:read`, `game-recommender:data:write`, `game-recommender:results:read`

**Important:** If you have both products, shared datasets (`bets`, `users`) must be uploaded using **only one scope** to avoid data duplication.

Choose either:

* Upload all shared data with `vip-intelligence:data:write`
* Upload all shared data with `game-recommender:data:write`

{% hint style="danger" %}
[**Do not upload the same data with both scopes - this will result in duplicate processing and billing.**](#user-content-fn-1)[^1]
{% endhint %}

### Scope Mapping by Endpoint

#### Data Upload Endpoints

<table data-full-width="true"><thead><tr><th width="305.5546875">Endpoint</th><th>Required Scope(s)</th></tr></thead><tbody><tr><td><code>POST /v1/data/bets</code></td><td><code>vip-intelligence:data:write</code> OR <code>game-recommender:data:write</code></td></tr><tr><td><code>POST /v1/data/bets-daily</code></td><td><code>vip-intelligence:data:write</code> OR <code>game-recommender:data:write</code></td></tr><tr><td><code>POST /v1/data/users</code></td><td><code>vip-intelligence:data:write</code> OR <code>game-recommender:data:write</code></td></tr><tr><td><code>POST /v1/data/vip-users</code></td><td><code>vip-intelligence:data:write</code></td></tr><tr><td><code>POST /v1/data/balances-daily</code></td><td><code>vip-intelligence:data:write</code></td></tr><tr><td><code>POST /v1/data/payments</code></td><td><code>vip-intelligence:data:write</code></td></tr><tr><td><code>POST /v1/data/payments-daily</code></td><td><code>vip-intelligence:data:write</code></td></tr></tbody></table>

**Note:** Shared datasets (bets, users) accept either product scope since the data storage is unified across products.

#### Game Recommender Endpoints

<table data-full-width="true"><thead><tr><th>Endpoint</th><th>Required Scope</th></tr></thead><tbody><tr><td><code>POST /recommendations/main</code></td><td><code>game-recommender:results:read</code></td></tr><tr><td><code>POST /recommendations/similar_games</code></td><td><code>game-recommender:results:read</code></td></tr></tbody></table>

***

### Best Practices

#### Separate Tokens for Different Services

For enhanced security, create different tokens for different parts of your infrastructure:

**ETL/Data Pipeline (upload only):**

```bash
scope=game-recommender:data:write
```

**Production API (read only):**

```bash
scope=game-recommender:results:read
```

**Benefit:** If one token is compromised, the impact is limited to its specific scope.

***

### FAQ

**Q: Can I use one token for all operations?**

A: Yes, you can request all scopes in a single token. However, for better security, we recommend using separate tokens for different services (ETL vs production API).

**Q: What happens if I request a scope I'm not subscribed to?**

A: The authentication server will return an error. You can only request scopes that match your product subscription.

**Q: How do I know which scopes I have access to?**

A: Contact your account manager or check your onboarding documentation. Your allowed scopes are configured during setup.

**Q: Can scopes be updated after initial setup?**

A: Yes, if you purchase additional products or upgrade your subscription, your available scopes will be updated. Contact support for scope modifications.

[^1]:
