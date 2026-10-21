"""Render an original 3D dodecahedron icon (12 pentagonal faces)."""

import itertools
import math
import sys

from PIL import Image, ImageDraw, ImageFilter

phi = (1 + 5**0.5) / 2
V = []
for s in itertools.product((-1, 1), repeat=3):
    V.append(s)
for a, b in itertools.product((-1, 1), repeat=2):
    V += [(0, a / phi, b * phi), (a / phi, b * phi, 0), (a * phi, 0, b / phi)]
N = []  # face normals = icosahedron vertices
for a, b in itertools.product((-1, 1), repeat=2):
    N += [(0, a * phi, b), (a * phi, b, 0), (a, 0, b * phi)]


def norm(v):
    length = math.sqrt(sum(c * c for c in v))
    return tuple(c / length for c in v)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def rot(v, ax, ay):
    x, y, z = v
    y, z = y * math.cos(ax) - z * math.sin(ax), y * math.sin(ax) + z * math.cos(ax)
    x, z = x * math.cos(ay) + z * math.sin(ay), -x * math.sin(ay) + z * math.cos(ay)
    return (x, y, z)


AX, AY = math.radians(-30), math.radians(20)
faces = []
for n in N:
    n = norm(n)
    vs = [v for v in V if abs(dot(norm(v), n) - max(dot(norm(w), n) for w in V)) < 1e-6]
    assert len(vs) == 5, len(vs)
    c = tuple(sum(v[i] for v in vs) / 5 for i in range(3))
    u = norm(cross(n, (0.3, 0.7, 0.2)))
    w = cross(n, u)
    vs.sort(
        key=lambda v: math.atan2(
            dot([v[i] - c[i] for i in range(3)], w),
            dot([v[i] - c[i] for i in range(3)], u),
        )
    )
    faces.append((rot(n, AX, AY), [rot(v, AX, AY) for v in vs]))

S, SS = 1024, 2
W = S * SS
img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle(
    (40 * SS, 40 * SS, W - 40 * SS, W - 40 * SS),
    radius=220 * SS,
    fill=(26, 31, 44, 255),
)

scale = 205 * SS
cx = cy = W / 2


def P(v):
    return (cx + v[0] * scale, cy - v[1] * scale)


light = norm((-0.45, 0.75, 0.6))
# soft shadow under the solid
sh = Image.new("RGBA", (W, W), (0, 0, 0, 0))
ImageDraw.Draw(sh).ellipse(
    (cx - 300 * SS, cy + 330 * SS, cx + 300 * SS, cy + 410 * SS), fill=(0, 0, 0, 150)
)
img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(40 * SS)))
d = ImageDraw.Draw(img)

visible = [(n, vs) for n, vs in faces if n[2] > 0.06]
visible.sort(key=lambda f: sum(v[2] for v in f[1]))
top = max(visible, key=lambda f: dot(f[0], norm((0.0, 0.3, 0.95))))  # lit "active" face
for n, vs in visible:
    k = max(0.0, dot(n, light))
    base = 70 + 175 * (0.25 + 0.75 * k)
    col = (int(base * 0.93), int(base * 0.96), int(base))
    if n is top[0]:
        col = (255, 190, 70)
    pts = [P(v) for v in vs]
    d.polygon(pts, fill=col + (255,))
    d.line(pts + [pts[0]], fill=(20, 24, 34, 255), width=7 * SS, joint="curve")
    if n is top[0]:
        d.polygon(pts, outline=(255, 225, 150, 255))

out = img.resize((S, S), Image.LANCZOS)
base = sys.argv[1] if len(sys.argv) > 1 else "custom_components/nanoleaf_remote/brand"
out.resize((256, 256), Image.LANCZOS).save(f"{base}/icon.png")
out.resize((512, 512), Image.LANCZOS).save(f"{base}/icon@2x.png")
