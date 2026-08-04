> For the complete documentation index, see [llms.txt](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/vip-intelligence/non-promising-vip-filtering-model.md).

# Non-Promising VIP Filtering Model

## Overview

The Non-Promising VIP Filtering Model identifies VIP players in entry-level segments who will not progress to higher VIP tiers within a defined timeframe, enabling operators to optimize VIP manager resources and focus attention on players with demonstrated growth potential.

Traditional VIP management treats all lower-segment VIP players equally, creating significant capacity constraints as these tiers typically contain the largest concentration of VIP members. The model analyzes player behavior patterns to identify those who will not advance beyond their current tier (either maintaining their level or declining), allowing operators to implement differentiated engagement strategies without compromising overall VIP program performance.

{% hint style="info" %}
**Configuration Note:** This documentation uses example values from typical iGaming operations. All parameters—including timeframes, thresholds, and VIP criteria—are configurable during implementation to match your specific business context.
{% endhint %}

### Key Benefits

**Resource Optimization:** Free VIP manager capacity by reassigning non-promising players to automated workflows, enabling team expansion without proportional hiring and allowing managers to focus on high-potential players.

**Proven Cost Reduction:** Demonstrable payroll savings through strategic resource reallocation, with impact scaling based on VIP population size and current team structure.

**Maintained VIP Performance:** Reassigned players maintain active VIP status with stable deposit frequency, gaming activity, and net gaming revenue metrics, validating that automated workflows deliver appropriate service quality.

**Scalable Operations:** Enable VIP program growth and improved service quality for high-potential players without increasing team size, addressing the fundamental capacity constraint in VIP management.

**Data-Driven Prioritization:** Replace intuition-based resource allocation with systematic identification of players who require intensive personal attention versus those who can be effectively served through automated channels.

## Data Requirements

### Minimum Historical Data Period

**Minimum 6** months of recent historical data (additional months may improve accuracy). This period must include:

* Sufficient VIP churn events to learn behavior patterns
* Complete player activity data to validate predictions
* Coverage across seasonal variations in player behavior

{% hint style="danger" %}
**Important:** Historical data should be recent and continuous (e.g., the most recent 6 months), not from several years ago, to ensure the model captures current player behavior patterns.
{% endhint %}

### Data Volume Requirements

The training dataset must include **complete VIP segment transition history** for all VIP players, showing movements between segments over time. This includes players who remained stable, progressed to higher tiers, and regressed to lower tiers. Daily granularity.

### Data Quality Requirements

* **Completeness:** No missing data for required fields. Optional fields can have null values.
* **Consistency:** Accurate data reflecting real operations. Test accounts and fraudulent activity should be excluded or marked with appropriate flags (e.g., `is_test_user: true`, `is_valid: false`).
* **Format:** Data can be provided either as individual transactions or daily aggregates as specified in the API documentation.
* **VIP Definition:** Complete specification of your VIP criteria, including metrics, calculation periods, thresholds, and any conditional logic.

## Business Process Context

VIP departments face a fundamental resource constraint: lower VIP tiers contain the largest player populations but receive the least manager attention due to limited team capacity. Without systematic prioritization, VIP managers distribute attention equally across all lower-tier VIP players, resulting in insufficient engagement for some players and excessive resource investment in others. This creates a compounding problem where manager capacity remains constrained by the total player population.

The Non-Promising VIP Filtering Model addresses this by identifying which players will not progress beyond their current tier, enabling operators to implement differentiated service strategies. Players identified as non-promising can be transitioned to automated engagement workflows or contact center management, freeing dedicated VIP managers to focus on the remaining player population where progression potential has not been ruled out.

## Required Data Fields

The model requires the following data types for both training and prediction:

* `deposits` - deposit transactions **(critical)**
* `vip_segments` - VIP segment assignments with timestamps **(critical)**
* `user_data` - user profile information **(critical)**
* `withdrawals` - withdrawal transactions **(recommended)**
* `bets` - betting activity **(recommended)**
* `wins` - winnings **(optional)**

{% hint style="info" %}
Refer to the Data Upload API documentation for detailed field specifications, formats, and upload procedures.
{% endhint %}

## Working with Predictions

### Understanding Prediction Output

The model outputs prediction scores (ranging from 0 to 100) for each player, indicating the probability that the player will NOT progress to a higher VIP segment within the defined evaluation period. Higher scores indicate a higher likelihood of maintaining the current segment without progression.

The model provides both probability scores (0 to 1) and binary classifications (1 = stable/non-promising, 0 = not classified as stable) for operational convenience.

Operators can choose to:

* Use the **classification results** for immediate player flagging and workflow assignment
* Use the **prediction scores** to create custom segmentation tiers based on available manager capacity and desired precision levels

### Threshold Configuration

Players are classified as non-promising when their scores exceed a defined threshold. The threshold determines the balance between coverage (how many players are identified) and precision (how accurate the identifications are).

**Threshold Selection Considerations:**

**VIP Manager Capacity:** How many players can be reassigned without overwhelming alternative service channels? Higher thresholds identify fewer players with higher confidence.

**Service Quality Objectives:** What level of personalized attention should non-promising players receive? Lower thresholds enable broader automation but increase false positive risk.

**Segment Progression Rates:** Operators with higher natural progression rates may prefer higher thresholds to minimize incorrect reassignments.

**Trade-offs:**

* **Lower thresholds** (e.g., 40-60 range): Identify more players as non-promising, enabling greater resource reallocation but with increased risk of incorrectly flagging players who would have progressed. Best for operators with severe capacity constraints or robust automated engagement systems.
* **Higher thresholds** (e.g., 70-85 range): Identify fewer players with higher confidence, minimizing false positives but capturing a smaller portion of non-promising players. Best for operators with moderate capacity constraints or premium service standards.

{% hint style="warning" %}
Note: Optimal threshold values are model-specific and determined through validation testing on your data, and depend on your retention team capacity and business objectives.
{% endhint %}

## Use Cases

### Automated Workflow Reassignment

**Objective:** Free VIP manager capacity by reassigning non-promising players to automated contact center workflows, enabling managers to focus on players who have not been identified as non-promising during the critical relationship-building phase.

**How It Works:** The model scores all lower-tier VIP players daily. Players exceeding the threshold are flagged for reassignment to contact center management, where they receive professional service through standardized scripts, automated communications, and scheduled touchpoints rather than dedicated personal manager attention. VIP managers reallocate their time to players not flagged as non-promising, providing intensive engagement to those where progression has not been ruled out.

**Hypothesis:** Players identified as non-promising can maintain satisfaction and activity levels through professional contact center service, while VIP managers generate better returns by concentrating effort on players not ruled out as non-promising. The capacity freed by workflow reassignment enables better service quality for the remaining player population without reducing overall VIP engagement.

**Business Impact:**

* Strategic manager reallocation from stable to high-potential VIP segments
* Proven stability: identified players maintain VIP activity with reduced engagement
* Cost-efficient program scaling without proportional team growth

**Implementation:** Integrate daily predictions with VIP manager assignment systems. Configure automated alerts for players crossing the threshold and implement workflow routing to contact center queues. Establish performance monitoring dashboards to track activity, retention, and financial metrics for reassigned players.

### Bonus and Promotion Optimization

**Objective:** Reduce bonus spending on players identified as non-promising while maintaining program attractiveness, reallocating promotional budget to players where progression has not been ruled out.

**How It Works:** Integrate prediction scores with bonus eligibility and allocation systems. Players identified as non-promising receive standard automated bonus offers based on activity triggers. Players not identified as non-promising receive enhanced bonus packages with personalized timing and structure. Promotional budget shifts from broad distribution to focused investment.

**Hypothesis:** Players identified as non-promising maintain activity with standard automated bonuses, while focusing enhanced promotional investment on the remaining player population generates superior ROI compared to equal distribution across all players.

**Business Impact:**

* Reduced total bonus expenditure through differentiated allocation
* Increased efficiency of promotional spending by focusing on appropriate player segments
* Improved promotional ROI through concentration on players not identified as non-promising
* Maintained engagement among non-promising players through appropriate baseline offers
* Data-driven promotional strategy replacing intuition-based allocation

Implementation: Integrate prediction scores with bonus management platforms. Configure differentiated bonus triggers and amounts based on score bands. Monitor progression rates and promotional response across score segments to optimize allocation rules over time.

### Model Limitations

Understanding model constraints helps set appropriate expectations:

* **Prediction horizon:** The model predicts non-progression within a specific timeframe (example: 90 days). Different horizons can be configured during implementation.
* **Data quality dependency:** Model accuracy directly depends on data quality, completeness, and consistency. Incomplete or inconsistent data will degrade predictions.
* **VIP criteria changes:** If you modify tier assignment logic, the model requires retraining. Significant changes may necessitate new model development.
* **Promotional impact:** Temporary campaigns or bonus structures may reduce prediction accuracy during campaign periods. Model performance is optimized for standard operational conditions.
* **Complete feature set required:** All required data fields must be provided for accurate predictions. Missing optional fields may reduce accuracy.
* **Context specificity:** Models are trained for each operator's specific context and cannot be transferred.

## Integration Overview

**High-level workflow:**

1. **Data Upload:** Submit historical data via Data Upload API
2. **Model Training:** Automated training process (initiated by MICo team)
3. **Predictions:** Daily predictions delivered via API
4. **Business Application:** Integrate predictions into your CRM, retention platform, or business process
5. **Monitoring:** Track outcomes and optimize strategy

The model operates autonomously once deployed. MICo continuously monitors model performance and handles retraining as needed to maintain prediction quality.

For detailed API specifications and integration examples, refer to the API Reference documentation.
