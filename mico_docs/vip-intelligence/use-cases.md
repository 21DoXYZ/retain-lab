> For the complete documentation index, see [llms.txt](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.mico.team/X5jRoDnFziWouDZp5RQv/vip-intelligence/use-cases.md).

# Use Cases

### Use Cases

#### Use Case 1: Early VIP Engagement + Capacity Optimization

**Challenge:** Traditional approaches identify VIPs too late AND retention teams lack capacity to work with all VIPs effectively.

**Solution:** Early detection combined with efficient capacity allocation through filtering.

**How it works:**

**Step 1: Early Identification (Days 3-7)**

* Monitor `previp` predictions for new players
* Identify high-probability VIP candidates
* Trigger immediate engagement: personalized bonuses, manager assignment

**Step 2: Optimize Retention Capacity**

* Once converted to VIP, check `stable-vip` predictions
* **Identified as stable** (score >0.7) → Automated programs only
* **Not identified as stable** → Active retention pipeline with manager attention

**Business Impact:**

* 20-30% faster VIP conversion through early engagement
* 30-40% more VIPs receive manager attention through efficient filtering
* Higher retention ROI by focusing limited resources on actionable players

***

#### Use Case 2: Churn Prevention with Resource Prioritization

**Challenge:** VIP retention teams have limited capacity (\~5 players per manager per day), but hundreds of VIPs show churn risk. Which ones deserve manager attention?

**Solution:** Identify at-risk VIPs, then filter out those unlikely to respond to intervention.

**How it works:**

**Step 1: Identify At-Risk VIPs**

* Monitor `vip-churn` predictions daily
* Flag players with high churn probability (score >0.7)

**Step 2: Filter Stable VIPs**

* Cross-reference at-risk VIPs with `stable-vip` predictions
* **High churn + Stable** (stable score >0.7) → Automated campaigns only
* **High churn + Not stable** → Manager intervention queue

**Step 3: Daily Prioritization**

* Managers focus on top 5 at-risk non-stable VIPs
* Automated systems handle stable VIPs

**Business Impact:**

* 85% churn detection ensures no valuable player is missed
* 40-50% reduction in wasted manager time on unresponsive VIPs
* Scalable approach handles growing VIP base without proportional headcount increase

***

#### Use Case 3: Full Lifecycle Management

**Challenge:** Managing players from acquisition to VIP maturity requires different strategies at each stage, but fragmented tools create operational complexity.

**Solution:** Unified prediction framework that provides clear actions at every player lifecycle stage.

**How it works:**

**Stage 1: New Player Acquisition (Days 1-7)**

* **Model:** `previp` identifies high-probability VIP candidates
* **Action:** Accelerated onboarding, personalized welcome bonuses
* **Goal:** Convert to VIP in days instead of weeks

**Stage 2: VIP Retention (Ongoing)**

* **Models:** `vip-churn` monitors disengagement risk + `stable-vip` filters capacity
* **Action:** Focus manager attention on at-risk non-stable VIPs, automate stable VIPs
* **Goal:** Prevent churn while optimizing resource allocation

**Stage 3: Portfolio Management**

* **Combined view:** All three models provide complete VIP portfolio visibility
* **Action:** Segment VIPs into treatment tiers based on conversion potential, churn risk, and stability
* **Goal:** Data-driven allocation of retention budget and manager capacity

**Business Impact:**

* Single integrated workflow replaces fragmented point solutions
* Clear action framework for each player lifecycle stage
* Measurable improvement in conversion time, churn rate, and retention ROI
* Efficient scaling as VIP base grows

***
