# CUDA / GPU Acceleration Support

The system should use CUDA-based GPU acceleration for performance-critical processing stages.

CUDA should be utilized for:

```text
- PARE inference
- SMPL reconstruction
- MediaPipe / pose model inference if supported
- segmentation model inference
- batch image processing
- tensor operations and beta fusion
```

---

# GPU Execution Strategy

If CUDA is available:

```python
device = "cuda"
```

Otherwise:

```python
device = "cpu"
```

The system must support both execution modes.

---

# Recommended Device Selection

```python
import torch

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
```

All models and tensors should be moved to the selected device:

```python
model.to(device)
tensor = tensor.to(device)
```

---

# Batch Processing Recommendation

Since the system always receives exactly 4 images:

```text
front_a
side
back_a
front_t
```

they should be processed as a batch whenever possible.

Recommended:

```text
Batch size = 4
```

This significantly reduces total inference time compared to processing each image independently.

---

# Performance Optimization Notes

CUDA acceleration is especially important for:

```text
- PARE inference
- SMPL forward passes
- tensor-based operations
- repeated mesh processing
```

For geometry operations based on:

* NumPy
* ConvexHull
* slicing

CPU execution is still acceptable unless these operations are later rewritten using PyTorch/CUDA.

---

# Mixed Precision Optimization

If model accuracy remains stable, mixed precision may be enabled:

```python
with torch.no_grad():
    with torch.cuda.amp.autocast():
        output = model(input_tensor)
```

Benefits:

* Faster inference
* Lower VRAM usage
* Higher throughput

---

# Important Rule

CUDA should improve performance only.

It must NOT:

* change measurement logic
* produce different measurement outputs between CPU and GPU

The system should remain as deterministic as possible.

---

# Pipeline Updates

The processing flow should change from:

```text
Run PARE per image
```

to:

```text
Run PARE on GPU in batch if CUDA is available
```

Additionally:

```text
Build Consensus SMPL Mesh
```

should become:

```text
Build Consensus SMPL Mesh on GPU if supported
```

---

# Final Goal

The system should:

* automatically detect CUDA availability
* use GPU acceleration whenever possible
* safely fall back to CPU execution if CUDA is unavailable
* improve performance without affecting measurement accuracy
