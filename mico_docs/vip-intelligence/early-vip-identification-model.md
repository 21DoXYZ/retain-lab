> For the complete documentation index, see [llms.txt](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/vip-intelligence/early-vip-identification-model.md).

# Early VIP Identification Model

## Overview

The Early VIP Identification system provides progressive predictions during a player's first week of activity, enabling identification of high-value players before they establish loyalty to competing platforms.

The system makes multiple predictions as behavioral data accumulates throughout the first week, with each prediction refining accuracy as more player activity is observed. The model identifies players who will achieve your operator-defined VIP threshold based on your specific VIP criteria (e.g., cumulative deposits, net gaming revenue, or custom metrics).

{% hint style="info" %}
Configuration Note: This documentation uses example values from typical iGaming operations. All parameters—including timeframes, thresholds, and VIP criteria—are configurable during implementation to match your specific business context.
{% endhint %}

### Key Benefits

* **Accelerated VIP Identification:** 3-6x faster than industry standard (days vs weeks)
* **Higher Conversion Rates:** 1,5-3x increase in VIP conversion rate
* **Enhanced Retention:** Early manager assignment resulted in 30-60% improvement in 30-day retention
* **Increased Revenue:** 30-100% higher deposit amounts and frequency
* **Competitive Advantage:** Engage high-value players before competitors

## Data Requirements

### Minimum Historical Data Period

**Minimum 6** months of recent historical data (additional months may improve accuracy). This period must include:

* Sufficient VIP churn events to learn behavior patterns
* Complete player activity data to validate predictions
* Coverage across seasonal variations in player behavior

{% hint style="danger" %}
**Important:** Historical data should be recent and continuous (e.g., the most recent 6 months), not from several years ago, to ensure the model captures current player behavior patterns.
{% endhint %}

### Data Quality Requirements

* **Completeness:** No missing data for required fields. Optional fields can have null values.
* **Consistency:** Accurate data reflecting real operations. Test accounts and fraudulent activity should be excluded or marked with appropriate flags (e.g., `is_test_user: true`, `is_valid: false`).
* **Format:** Data can be provided either as individual transactions or daily aggregates as specified in the API documentation.
* **VIP Definition:** Complete specification of your VIP criteria, including metrics, calculation periods, thresholds, and any conditional logic.

## Business Process Context

Traditional VIP identification takes 30+ days, by which time many high-value players have migrated to competitors. This model identifies promising players within their first week of activity during the critical exploration phase.

From thousands of new daily depositors, the system analyzes potential VIP candidates daily, enabling managers to establish relationships before competitors can engage.

## Required Data Fields

The model requires the following data types for both training and prediction:

* `deposits` - deposit transactions
* `withdrawals` - withdrawal transactions
* `bets` - betting activity
* `wins` - winnings
* `vip_statuses` - VIP segment assignments with timestamps
* `user_data` - user profile information (country is optional but recommended)

{% hint style="info" %}
Refer to the Data Upload API documentation for detailed field specifications, formats, and upload procedures.
{% endhint %}

## Working with Predictions

### Understanding Probability Scores

The model outputs prediction scores (ranging from 0 to 100) for each player, along with classification results (0 = non-VIP, 1 = potential VIP). Higher scores indicate higher probability of achieving VIP status.

Operators can choose to:

* Use the **classification results** for immediate player flagging
* Use the **prediction scores** to apply custom thresholds based on operational capacity

### Coverage vs Precision Trade-off

Players are classified as potential VIPs when their scores exceed a defined threshold. Threshold selection depends on:

* **VIP Manager Capacity:** How many players can your team actively engage?
* **False Positive Tolerance:** What percentage of non-VIP identifications is acceptable?
* **Business Strategy:** Maximize coverage (lower threshold) or precision (higher threshold)?

**Trade-offs:**

* **Lower thresholds:** Capture more future VIPs (higher recall) but generate more false positives. Best for maximizing VIP population.
* **Higher thresholds:** Reduce false positives (higher precision) but miss some borderline cases. Best for limited resources or high-touch engagement strategies.

Optimal thresholds are determined during model training and validation using your historical data, and depend on your VIP manager capacity and business objectives..&#x20;

## Use Cases

### Accelerated VIP Manager Assignment

**Objective:** Assign dedicated VIP managers to high-potential players within their first week of activity, preventing competitor acquisition during the critical exploration phase.

**How It Works:** The model scores new depositors daily. Players exceeding the threshold are flagged for immediate manager assignment. Managers establish personal contact while players are still exploring platform options.

**Hypothesis:** Early personal contact establishes relationship and loyalty before players explore alternative platforms. New players haven't yet committed to a preferred operator, making this the optimal window for relationship-building.

**Business Impact:**

* Higher retention through early relationship building
* Faster VIP status achievement through proactive engagement
* Prevention of high-value player migration to competitors
* Increased total VIP population through early intervention

**Implementation:** Integrate predictions with VIP manager CRM dashboard and configure automated alerts for threshold-exceeding players.

### Resource Optimization

**Objective:** Focus VIP manager efforts on players with highest conversion probability, maximizing team efficiency and ensuring resources are allocated to players most likely to become valuable long-term customers.

**How It Works:** Use probability scores to prioritize the engagement queue. Allocate premium resources (personal calls, exclusive gifts, dedicated manager attention) to highest-scoring players. Lower-scoring players receive automated engagement or standard marketing flows.

**Hypothesis:** Not all identified players have equal VIP potential. Focusing intensive resources on highest-probability players generates better ROI than uniform treatment of all flagged players.

**Business Impact:**

* Higher VIP manager efficiency through better prioritization
* Improved conversion rates by focusing on best opportunities
* Reduced cost per VIP acquisition
* Better resource allocation across the player lifecycle
* Scalable VIP program growth without proportional team expansion

**Implementation:** Sort identified players by probability score and distribute them among available VIP managers based on your team capacity. Managers actively engage with assigned players through personal outreach, building relationships during the critical first-week window.

## Model Limitations

Understanding model constraints helps set appropriate expectations:

* **Data Quality Dependency:** Model accuracy directly depends on data quality and consistency. Incomplete or inconsistent data degrades predictions.
* **Complete Feature Set Required:** All required data fields must be provided for accurate predictions. Missing optional fields may reduce accuracy.
* **Historical Data Requirement:** Operators need sufficient historical data (6-12 months with VIP conversions) before initial model training.

## Integration Overview

**High-level workflow:**

1. **Data Upload:** Submit historical data via Data Upload API
2. **Model Training:** Automated training process (initiated by MICo team)
3. **Predictions:** Daily predictions delivered via API
4. **Business Application:** Integrate predictions into your CRM, retention platform, or business process
5. **Monitoring:** Track outcomes and optimize strategy

The model operates autonomously once deployed. MICo continuously monitors model performance and handles retraining as needed to maintain prediction quality.

For detailed API specifications and integration examples, refer to the API Reference documentation.
