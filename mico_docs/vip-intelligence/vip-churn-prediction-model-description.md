> For the complete documentation index, see [llms.txt](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/vip-intelligence/vip-churn-prediction-model-description.md).

# VIP Churn Prediction Model  Description

## Overview

The VIP Churn Prediction Model identifies VIP players at risk of churning within a defined future period. Churn is defined based on your specific criteria (e.g., no deposits for a consecutive number of days).

This model enables a fundamental shift from reactive to proactive customer relationship management. Instead of responding after players have already stopped depositing, operators can identify at-risk VIPs early and intervene while they're still engaged with the platform.

{% hint style="info" %}
Configuration Note: This documentation uses example values from typical iGaming operations. All parameters—including timeframes, thresholds, and VIP criteria—are configurable during implementation to match your specific business context.
{% endhint %}

### **Key Benefits:**

* Early identification of churn risk before players become inactive
* Prioritized resource allocation for retention teams
* Data-driven intervention strategies
* Reduced churn rates through timely engagement

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

Traditional VIP retention relies on reactive rules (e.g., 14-30 days without deposits), by which time players may have already disengaged or migrated to competitors. This model enables proactive identification of churn risk, allowing intervention while players are still active.

Understanding your VIP criteria and manager capacity helps configure the model to identify the right volume of candidates and optimize resource allocation for your team.

### Required Data Fields

The model requires the following data types for both training and prediction.&#x20;

* `deposits` - deposit transactions **(critical)**
* `user_data` - user profile information (registration date, VIP status date, country) **(critical)**
* `withdrawals` - withdrawal transactions **(recommended)**
* `bets` - betting activity **(recommended)**
* `failed_deposits` - failed deposit attempts **(recommended)**
* `wins` - winnings **(optional)**
* `balance` - end-of-day player balance **(optional)**
* `fees` - payment and provider fees **(optional)**
* `sessions` - user session data **(optional)**

{% hint style="info" %}
Refer to the Data Upload API documentation for detailed field specifications, formats, and upload procedures.
{% endhint %}

## Working with Predictions

### Understanding Probability Scores

The model returns a probability score between 0 and 1 for each VIP player, indicating the likelihood of churn within the defined prediction period. Higher scores indicate higher churn risk.

### Threshold Configuration

A threshold is a boundary value that determines which players are classified as "at risk of churn." Players with scores above the threshold are flagged for retention actions, while those below continue normal engagement.

**Example threshold values for VIP Churn model:**

* **0.5** - Balanced approach
* **0.7** - Moderate precision focus
* **0.9** - High precision focus

{% hint style="warning" %}
Note: Optimal threshold values are model-specific and determined through validation testing on your data, and depend on your retention team capacity and business objectives.
{% endhint %}

### Coverage vs Precision Trade-off

Selecting a threshold involves balancing two competing objectives:

**Lower thresholds (e.g., 0.5):**

* **Higher coverage:** Capture more players who will actually churn
* **More false positives:** Include players who won't actually churn
* **Best for:** Maximum retention effort, new retention programs, high-value player segments

**Higher thresholds (e.g., 0.9):**

* **Higher precision:** Focus on players most likely to churn
* **Lower coverage:** Miss some players who will churn
* **Best for:** Limited retention resources, proven intervention strategies, cost optimization

## Use Cases

### Proactive Retention Communications

**Objective:** Identify VIP players at risk of churning before they stop depositing, enabling timely retention interventions.

**How it works:** The model predicts churn risk in advance. When a player's score exceeds your configured threshold, trigger personalized retention communications such as exclusive bonuses, personal manager outreach, VIP event invitations, or customized offers.

**Hypothesis:** Proactive contact with players predicted as high churn risk prevents actual churn by re-engaging players while they're still active on the platform.

**Business Impact:**

* Reduced churn rate → Increased active player base → Revenue growth
* Earlier intervention = higher success rate vs late-stage retention efforts
* Improved player lifetime value through extended engagement periods

**Implementation:** Integrate predictions with your CRM or retention platform. Set up automated workflows that trigger appropriate communications based on churn score and player segment.

### Resource Optimization

**Objective:** Focus retention team efforts on players where intervention has the highest probability of success, reducing wasted resources on players who will churn regardless of outreach.

**How it works:** Use prediction confidence levels to prioritize retention queue. Allocate premium resources (personal calls, exclusive gifts) to players with moderate churn risk where intervention makes a difference. Reduce or eliminate outreach to players with very high certainty of churn or very low risk.

**Hypothesis:** The model identifies players who will churn regardless of intervention. By reducing communication with these players, you reduce retention costs without impacting churn rates.

**Business Impact:**

* Reduced retention operation costs → Improved business profitability
* Higher retention team efficiency → Better resource allocation
* Improved player experience (reduced spam to loyal players)
* Higher ROI on retention investments

**Implementation:** Segment your predicted churn list by score ranges. Define different intervention strategies for each segment. Monitor cost per retained player and optimize threshold accordingly.

## Model Limitations

Understanding model constraints helps set appropriate expectations:

* **Prediction horizon:** The model predicts churn within a specific timeframe (typically 30 days). Different prediction horizons can be configured during implementation.
* **Historical data requirement:** Sufficient historical data is needed for feature calculation on any given prediction date.
* **Complete Feature Set Required:** All required data fields must be provided for accurate predictions. Missing optional fields may reduce accuracy.
* **Data quality dependency:** Model accuracy directly depends on data quality and consistency
* **Context specificity:** Models are trained for each operator's specific context and cannot be transferred

## Integration Overview

**High-level workflow:**

1. **Data Upload:** Submit historical data via Data Upload API
2. **Model Training:** Automated training process (initiated by MICo team)
3. **Predictions:** Daily predictions delivered via API
4. **Business Application:** Integrate predictions into your CRM, retention platform, or business process
5. **Monitoring:** Track outcomes and optimize strategy

The model operates autonomously once deployed. MICo continuously monitors model performance and handles retraining as needed to maintain prediction quality.

For detailed API specifications and integration examples, refer to the API Reference documentation.
