# User Demographic & Body Model Classification Update

The current system only collects:

* Gender
* Height
* Weight

This is not sufficient for accurate AI-based body measurement estimation.

The system must be updated to include age-based body modeling logic.

---

# Required User Inputs

The system should collect the following information:

## Required Fields

### 1. Gender

Options:

* Male
* Female

IMPORTANT:
Do NOT add “Child” as a gender option.

Child is not a gender category and must not appear alongside Male/Female.

---

### 2. Age

Add a required age field.

Recommended:

* Numeric age input
  or
* Date of birth input

Purpose:

* Improve body proportion estimation
* Improve anthropometric modeling
* Improve circumference prediction
* Improve skeletal ratio estimation

---

### 3. Height

Required numeric input.

Purpose:

* Scale normalization
* Body proportion calculations
* 3D body estimation

---

### 4. Weight

Required numeric input.

Purpose:

* Body volume estimation
* Circumference estimation
* Body fat approximation

---

# Why Age Is Critical

Body proportions differ significantly between:

* Children
* Teenagers
* Adults

Differences include:

* Head-to-body ratio
* Leg-to-torso ratio
* Shoulder width
* Hip structure
* Fat distribution
* Skeletal proportions

Using adult body assumptions for children causes major measurement inaccuracies.

---

# Required AI Classification Logic

The backend should automatically classify users into body-model groups based on age.

Recommended logic:

```python
if age < 13:
    body_model = "child"

elif age < 18:
    body_model = "teen"

else:
    body_model = "adult"
```

The classification should happen internally and should not require the user to choose manually.

---

# Recommended Internal Model Groups

Suggested body model categories:

* Child
* Teen
* Adult

This classification should influence:

* Body proportion priors
* Circumference estimation
* Skeletal scaling
* Pose interpretation
* Parametric body reconstruction

---

# AI Measurement Pipeline Integration

The age category should affect:

* Anthropometric ratios
* Multi-view reconstruction
* Body depth estimation
* Parametric model fitting
* Landmark interpretation

The system should avoid using the same proportional assumptions for all ages.

---

# Final Recommended User Form

The final form should contain:

```text
Gender
Age
Height
Weight
```

Recommended Gender Options:

```text
- Male
- Female
```

Age category derivation should happen automatically inside backend logic.

---

# Final Objective

The updated system should:

* Improve measurement precision across all age groups
* Reduce child/teen estimation errors
* Improve anthropometric realism
* Improve AI model stability
* Enable future dataset segmentation and model training optimization
