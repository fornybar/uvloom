from pathlib import Path

import matplotlib
import numpy as np
from meshpy.triangle import MeshInfo, build

matplotlib.use("Agg")

import matplotlib.pyplot as plt


def circle(cx: float, cy: float, radius: float, points: int) -> np.ndarray:
    angles = np.linspace(0.0, 2.0 * np.pi, points, endpoint=False)
    return np.column_stack([cx + radius * np.cos(angles), cy + radius * np.sin(angles)])


def loop_segments(start: int, count: int) -> list[tuple[int, int]]:
    return [(start + index, start + (index + 1) % count) for index in range(count)]


def plot_smiley(output: str | Path = "smiley.png") -> Path:
    output_path = Path(output)

    face = circle(0.0, 0.0, 1.0, 96)
    left_eye = circle(-0.35, 0.3, 0.13, 32)
    right_eye = circle(0.35, 0.3, 0.13, 32)

    mouth_points = 40
    mouth_x = np.linspace(-0.55, 0.55, mouth_points)
    mouth_bottom_y = -0.20 - 0.30 * (1.0 - (mouth_x / 0.55) ** 2)
    mouth_top_y = -0.20 - 0.08 * (1.0 - (mouth_x / 0.55) ** 2)
    mouth_bottom = np.column_stack([mouth_x, mouth_bottom_y])
    mouth_top = np.column_stack([mouth_x[::-1], mouth_top_y[::-1]])
    mouth = np.vstack([mouth_bottom[:-1], mouth_top[:-1]])

    loops = [face, left_eye, right_eye, mouth]
    points: list[np.ndarray] = []
    segments: list[tuple[int, int]] = []
    offset = 0

    for loop in loops:
        points.append(loop)
        segments.extend(loop_segments(offset, len(loop)))
        offset += len(loop)

    vertices_input = np.vstack(points)

    mesh_info = MeshInfo()
    mesh_info.set_points(vertices_input.tolist())
    mesh_info.set_facets(segments)
    mesh_info.set_holes([
        (-0.35, 0.3),
        (0.35, 0.3),
        (0.0, -0.35),
    ])

    mesh = build(mesh_info, max_volume=0.002, min_angle=28)

    vertices = np.array(mesh.points)
    triangles = np.array(mesh.elements)
    centroids = vertices[triangles].mean(axis=1)
    distance = np.linalg.norm(centroids, axis=1)

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.tripcolor(
        vertices[:, 0],
        vertices[:, 1],
        triangles,
        facecolors=distance,
        cmap="YlOrBr_r",
        edgecolors="#00000033",
        linewidth=0.3,
    )
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title("Smiley via meshpy (C++) + matplotlib")

    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return output_path
