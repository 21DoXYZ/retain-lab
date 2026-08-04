> For the complete documentation index, see [llms.txt](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/vip-intelligence/b2b-integration-architecture.md).

# B2B Integration Architecture

### Integration Flow Diagram

TBD

### Integration Points

#### 1. **Authentication** 🔐

```
POST /auth/token
```

* Obtain access token with API credentials
* Use token for all subsequent requests

#### 2. **Data Upload** 📤

```
POST /v1/data/users          - User profiles
POST /v1/data/bets           - Betting transactions
POST /v1/data/bets-daily     - Aggregated betting data
POST /v1/data/payments       - Payment transactions
POST /v1/data/payments-daily - Aggregated payments
POST /v1/data/vip-users      - VIP segments
POST /v1/data/balances-daily - Daily balances
```

#### 3. **Predictions Retrieval** 📊

```
GET /v1/predictions/previp            - Early VIP detection
GET /v1/predictions/vip-churn         - VIP churn prediction
GET /v1/predictions/stable-vip        - Non-promising VIP filtering
GET /v1/predictions/{model}/status    - Check data availability
```

#### 4. **Monitoring** 📈

* Web dashboards for API consumption metrics
* Model performance tracking
* Prediction analytics and insights
* Error monitoring and alerts

***

### Integration Options

#### Option A: Direct API Integration

* Implement API calls directly from your platform
* Full control over data flow
* Best for: Custom integrations, existing data pipelines

#### Option B: MICo SDK

* Pre-built library for data upload and prediction retrieval
* Simplified integration with error handling
* Best for: Faster implementation, standardized approach

***

### Data Flow Summary

```
Your Database → Authentication → Data Upload → ML Processing → 
→ Predictions Generation → Prediction Retrieval → Your CRM/BI
```

**Processing Time:** Models typically recalculate predictions daily

**Monitoring:** Real-time dashboards accessible 24/7
