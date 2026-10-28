"""Render the integration icon: a dodecahedron seen face-on, in white lines.

Same view as the product photos: one face towards the viewer with a vertex
pointing down and its five neighbours around it, tilted a little so the top
face shows. Needs Pillow (not a project dependency):

    python scripts/make_icon.py [output-dir]
"""

import itertools
import math
import sys

from PIL import Image, ImageDraw

phi = (1 + 5**0.5) / 2
VERTICES = [tuple(s) for s in itertools.product((-1, 1), repeat=3)]
for a, b in itertools.product((-1, 1), repeat=2):
    VERTICES += [(0, a / phi, b * phi), (a / phi, b * phi, 0), (a * phi, 0, b / phi)]
NORMALS = []  # face normals = icosahedron vertices
for a, b in itertools.product((-1, 1), repeat=2):
    NORMALS += [(0, a * phi, b), (a * phi, b, 0), (a, 0, b * phi)]

TILE = (14, 158, 224, 255)  # Home Assistant blue
WHITE = (255, 255, 255, 255)
TILT, YAW = math.radians(9), math.radians(-4)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b, strict=True))


def norm(v):
    length = math.sqrt(dot(v, v))
    return tuple(c / length for c in v)


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def face_vertices(normal):
    best = max(dot(norm(v), normal) for v in VERTICES)
    return [v for v in VERTICES if abs(dot(norm(v), normal) - best) < 1e-6]


def view_matrix():
    """Rows e_x, e_y, e_z: face 0 towards the viewer, a vertex pointing down."""
    n = norm(NORMALS[0])
    verts = face_vertices(n)
    centre = tuple(sum(v[i] for v in verts) / 5 for i in range(3))
    e_y = tuple(-c for c in norm(sub(verts[0], centre)))
    return [cross(e_y, n), e_y, n]


def turn(v):
    """Tilt (about x) then yaw (about y), both small."""
    x, y, z = v
    y, z = (
        y * math.cos(TILT) - z * math.sin(TILT),
        y * math.sin(TILT) + z * math.cos(TILT),
    )
    x, z = x * math.cos(YAW) + z * math.sin(YAW), -x * math.sin(YAW) + z * math.cos(YAW)
    return (x, y, z)


def visible_faces():
    basis = view_matrix()

    def to_view(v):
        return turn(tuple(dot(row, v) for row in basis))

    faces = []
    for normal in NORMALS:
        normal = norm(normal)
        if to_view(normal)[2] <= 0.05:
            continue
        verts = [to_view(v) for v in face_vertices(normal)]
        centre = tuple(sum(v[i] for v in verts) / 5 for i in range(3))
        n_view = to_view(normal)
        u = norm(cross(n_view, (0.3, 0.7, 0.2)))
        w = cross(n_view, u)
        verts.sort(
            key=lambda v: math.atan2(dot(sub(v, centre), w), dot(sub(v, centre), u))
        )
        faces.append((n_view, verts))
    return faces


def render(size: int = 1024, supersample: int = 3) -> Image.Image:
    faces = visible_faces()
    W = size * supersample
    points = [v for _, verts in faces for v in verts]
    mid = tuple(
        (max(p[i] for p in points) + min(p[i] for p in points)) / 2 for i in range(2)
    )
    extent = max(abs(p[i] - mid[i]) for p in points for i in range(2))
    scale = 0.36 * W / extent

    def project(v):
        return (W / 2 + (v[0] - mid[0]) * scale, W / 2 - (v[1] - mid[1]) * scale)

    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    margin = int(0.04 * W)
    d.rounded_rectangle(
        (margin, margin, W - margin, W - margin), radius=int(0.215 * W), fill=TILE
    )

    stroke = int(0.022 * W)
    front = max(faces, key=lambda f: f[0][2])
    for n, verts in sorted(faces, key=lambda f: sum(v[2] for v in f[1])):
        pts = [project(v) for v in verts]
        if (n, verts) == front:
            c = tuple(sum(v[i] for v in verts) / 5 for i in range(3))
            inner = [
                project(tuple(c[i] + (v[i] - c[i]) * 0.88 for i in range(3)))
                for v in verts
            ]
            d.polygon(inner, fill=WHITE)
        d.line(pts + [pts[0]], fill=WHITE, width=stroke, joint="curve")
        for x, y in pts:  # round the corners
            d.ellipse(
                (x - stroke / 2, y - stroke / 2, x + stroke / 2, y + stroke / 2),
                fill=WHITE,
            )
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    out = (
        sys.argv[1] if len(sys.argv) > 1 else "custom_components/nanoleaf_remote/brand"
    )
    icon = render()
    icon.resize((256, 256), Image.LANCZOS).save(f"{out}/icon.png")
    icon.resize((512, 512), Image.LANCZOS).save(f"{out}/icon@2x.png")
