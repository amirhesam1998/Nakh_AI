# AI Body Measurement Capture System — Pose Optimization Specification

We need to redesign and optimize the current body measurement capture flow for maximum balance between:

* Measurement precision
* User experience (UX)
* Landmark detection quality
* Multi-view body reconstruction accuracy

The current system should be updated based on the following specifications.

---

# Final Required Capture Flow

The system must use exactly 4 body capture images:

## 1. Front A-Pose

User stands facing the camera.

Requirements:

* Arms slightly separated from the body
* Feet slightly apart (~15–20 cm)
* Natural standing posture
* Full body visible from head to feet

Purpose:

* Chest width
* Waist contour
* Hip width
* Leg length
* Body proportions
* Primary front silhouette

---

## 2. Side Pose

User stands in full side profile.

Requirements:

* Natural posture
* Arms positioned to avoid covering torso
* Full body visible

Purpose:

* Body depth estimation
* Chest depth
* Abdomen projection
* Glute profile
* Posture analysis
* Accurate circumference estimation

IMPORTANT:
This is the most critical image for reducing circumference estimation error.

---

## 3. Back A-Pose

User faces away from the camera.

Requirements:

* Same stance as Front A-Pose
* Arms slightly separated
* Full body visible

Purpose:

* Back width
* Shoulder alignment
* Glute shape
* Leg symmetry
* Posterior body contour

---

## 4. Front T-Pose

User faces the camera with arms extended horizontally.

Requirements:

* Arms parallel to the ground
* Palms facing downward
* Body remains upright
* Full body visible

Purpose:

* Better arm segmentation
* Accurate shoulder width
* Underarm visibility
* Improved torso separation
* More accurate arm length extraction
* Cleaner body contour detection

---

# Removed Poses

The following poses should be removed from the system:

## Remove:

* Back T-Pose
* Arms vertically raised pose
* Any overhead arm pose

Reasons:

* Poor UX
* Unnatural body deformation
* Chest and shoulder distortion
* Increased user fatigue
* Low accuracy gain compared to added complexity

---

# Camera & Capture Requirements

These are mandatory for accurate measurements.

## Camera Distance

Use a fixed recommended distance.

Recommended:

* Approximately 2.5 meters

System should guide users visually.

---

## Camera Height

Camera should be positioned around hip level.

Avoid:

* High angle
* Low angle
* Perspective distortion

---

## Lens / Field of View

Avoid ultra-wide distortion.

Preferred equivalent:

* 35mm–50mm focal length

If mobile camera is wide-angle:

* Use center crop correction if possible

---

## Framing

Entire body must remain visible:

* Head fully visible
* Feet fully visible
* No cropped limbs

---

## Lighting

Require even lighting.

Avoid:

* Strong shadows
* Backlight
* Dark rooms

---

## Clothing Requirements

Users should wear:

* Tight or fitted clothing

Avoid:

* Oversized clothes
* Jackets
* Loose hoodies
* Long coats

These significantly reduce segmentation accuracy.

---

# AI Processing Pipeline Recommendations

The system should combine multiple techniques instead of relying only on silhouette extraction.

Recommended pipeline:

## 1. Human Segmentation

Use:

* MediaPipe
* BodyPix
* Detectron2
  or equivalent

Goal:

* Accurate body mask extraction

---

## 2. Pose Landmark Detection

Use:

* BlazePose
* OpenPose
* MediaPipe Pose

Goal:

* Extract skeletal landmarks
* Improve anatomical consistency

---

## 3. Multi-View Fusion

Combine:

* Front
* Side
* Back
* T-Pose

Goal:

* Reduce occlusion problems
* Improve depth estimation
* Improve circumference prediction

---

## 4. Parametric Human Body Modeling (Recommended)

If possible, integrate:

* SMPL
* SMPL-X

Goal:

* Reconstruct approximate 3D body shape
* Improve measurement realism
* Reduce estimation instability

---

# Measurement Extraction Strategy

Different measurements should use different pose sources.

Recommended logic:

| Measurement         | Preferred Source |
| ------------------- | ---------------- |
| Shoulder Width      | Front T-Pose     |
| Chest Circumference | Front A + Side   |
| Waist Circumference | Front A + Side   |
| Hip Circumference   | Back A + Side    |
| Arm Length          | Front T          |
| Torso Width         | Front A          |
| Back Width          | Back A           |
| Posture Analysis    | Side             |
| Body Depth          | Side             |

The AI should not rely on a single image for all measurements.

---

# UX Requirements

The flow must remain simple and fast.

Recommended sequence:

1. Front A-Pose
2. Side Pose
3. Back A-Pose
4. Front T-Pose

The UI should:

* Show pose examples
* Validate body visibility before capture
* Warn about bad lighting
* Warn about cropped body parts
* Detect improper distance automatically if possible

---

# Final Objective

The system should maximize:

* Measurement precision
* Landmark reliability
* Body contour accuracy
* Circumference estimation quality
* User completion rate

while minimizing:

* User fatigue
* Pose complexity
* Capture time
* Segmentation failure
* Perspective distortion
