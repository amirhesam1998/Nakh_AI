"""
Alpha-shape (concave hull) perimeter computation for cross-section slices.

Replaces ConvexHull with a tighter boundary that respects body concavities
(e.g. waist indentation, armpit gap). Falls back to ConvexHull when
alpha-shape extraction fails or produces degenerate geometry.
"""
import math

import numpy as np
from scipy.spatial import ConvexHull, Delaunay


def _circumradius(tri_pts: np.ndarray) -> float:
    """Circumradius of a triangle defined by 3 points in 2D."""
    a = float(np.linalg.norm(tri_pts[1] - tri_pts[0]))
    b = float(np.linalg.norm(tri_pts[2] - tri_pts[1]))
    c = float(np.linalg.norm(tri_pts[0] - tri_pts[2]))
    s = 0.5 * (a + b + c)
    area_sq = s * (s - a) * (s - b) * (s - c)
    if area_sq <= 0.0:
        return float("inf")
    area = math.sqrt(area_sq)
    if area < 1e-12:
        return float("inf")
    return (a * b * c) / (4.0 * area)


def alpha_shape_perimeter(
    pts: np.ndarray,
    alpha: float = 0.0,
) -> float:
    """Compute the perimeter of the alpha-shape boundary of *pts*.

    Parameters
    ----------
    pts : (N, 2) array
        2-D point cloud (centred cross-section slice).
    alpha : float
        Controls concavity.  ``alpha=0`` triggers automatic selection
        (``1 / median_edge_length``).  Larger values → tighter (more concave)
        boundary; very large values may split the shape.

    Returns
    -------
    float
        Perimeter length in the same units as *pts*, or ``np.nan`` on failure.
    """
    if pts.shape[0] < 3:
        return np.nan

    # Deduplicate close points (Delaunay can choke on duplicates)
    pts = _deduplicate(pts)
    if pts.shape[0] < 3:
        return np.nan

    try:
        tri = Delaunay(pts)
    except Exception:
        return _convex_fallback(pts)

    # Auto-alpha: 1 / median edge length of the Delaunay triangulation
    if alpha <= 0.0:
        alpha = _auto_alpha(pts, tri)

    threshold = 1.0 / alpha if alpha > 0 else float("inf")

    # Filter triangles whose circumradius exceeds the threshold
    keep_simplices = []
    for simplex in tri.simplices:
        cr = _circumradius(pts[simplex])
        if cr < threshold:
            keep_simplices.append(simplex)

    if not keep_simplices:
        return _convex_fallback(pts)

    # Extract boundary edges (edges that appear in exactly one triangle)
    edge_count: dict = {}
    for simplex in keep_simplices:
        for i in range(3):
            e = tuple(sorted((simplex[i], simplex[(i + 1) % 3])))
            edge_count[e] = edge_count.get(e, 0) + 1

    boundary_edges = [e for e, cnt in edge_count.items() if cnt == 1]
    if not boundary_edges:
        return _convex_fallback(pts)

    # Sum boundary edge lengths
    perimeter = sum(
        np.linalg.norm(pts[e[0]] - pts[e[1]]) for e in boundary_edges
    )
    return float(perimeter) if perimeter > 0 else np.nan


def _auto_alpha(pts: np.ndarray, tri: Delaunay) -> float:
    """Pick alpha as 1 / median_edge_length."""
    edges = set()
    for simplex in tri.simplices:
        for i in range(3):
            edges.add(tuple(sorted((simplex[i], simplex[(i + 1) % 3]))))
    lengths = [np.linalg.norm(pts[a] - pts[b]) for a, b in edges]
    if not lengths:
        return 1.0
    med = float(np.median(lengths))
    return 1.0 / max(med, 1e-8)


def _deduplicate(pts: np.ndarray, tol: float = 1e-6) -> np.ndarray:
    """Remove near-duplicate points."""
    if pts.shape[0] <= 3:
        return pts
    # Use integer grid rounding to avoid overflow with very small tol
    inv_tol = 1.0 / max(tol, 1e-12)
    rounded = np.round(pts * inv_tol).astype(np.int64)
    _, idx = np.unique(rounded, axis=0, return_index=True)
    return pts[np.sort(idx)]


def _convex_fallback(pts: np.ndarray) -> float:
    """Convex hull perimeter as fallback."""
    if pts.shape[0] < 3:
        return np.nan
    try:
        hull = ConvexHull(pts)
    except Exception:
        return np.nan
    verts = hull.vertices
    return float(sum(
        np.linalg.norm(pts[verts[i]] - pts[verts[(i + 1) % len(verts)]])
        for i in range(len(verts))
    ))
