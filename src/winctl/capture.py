"""Screen capture and formatting for model vision."""

from __future__ import annotations

import io
from dataclasses import dataclass

import mss
from PIL import Image, ImageDraw

from . import winapi


@dataclass
class Shot:
    png: bytes
    mime: str
    origin: tuple[int, int]
    real_size: tuple[int, int]
    sent_size: tuple[int, int]
    scale: float
    label: str

    def summary(self) -> str:
        rw, rh = self.real_size
        sw, sh = self.sent_size
        ox, oy = self.origin
        note = (
            f"Capture: {self.label} | real area {rw}x{rh} px at origin ({ox}, {oy}) "
            f"| image sent {sw}x{sh} (scale {self.scale:.3f})."
        )
        if self.scale != 1.0:
            note += (
                " Coordinates read on the image must be converted back: "
                f"x_real = {ox} + x_image / {self.scale:.3f}, y_real = {oy} + y_image / {self.scale:.3f}."
            )
        else:
            note += f" Add the origin to the coordinates read: x_real = {ox} + x_image, y_real = {oy} + y_image."
        return note


def monitors() -> list[dict]:
    with mss.mss() as sct:
        out = []
        for i, m in enumerate(sct.monitors):
            out.append(
                {
                    "index": i,
                    "role": "full virtual desktop" if i == 0 else f"monitor {i}",
                    "x": m["left"],
                    "y": m["top"],
                    "width": m["width"],
                    "height": m["height"],
                }
            )
        return out


def _draw_grid(img: Image.Image, origin: tuple[int, int], scale: float, step_real: int) -> None:
    """Draw a grid annotated with real screen coordinates.

    The labels show the real value, not the position in the resized image, so
    that the coordinates read are directly clickable.
    """
    draw = ImageDraw.Draw(img, "RGBA")
    ox, oy = origin
    w, h = img.size

    first_x = ((ox + step_real - 1) // step_real) * step_real
    x = first_x
    while (x - ox) * scale < w:
        px = int((x - ox) * scale)
        draw.line([(px, 0), (px, h)], fill=(255, 0, 128, 90), width=1)
        draw.text((px + 3, 3), str(x), fill=(255, 0, 128, 235))
        x += step_real

    first_y = ((oy + step_real - 1) // step_real) * step_real
    y = first_y
    while (y - oy) * scale < h:
        py = int((y - oy) * scale)
        draw.line([(0, py), (w, py)], fill=(0, 160, 255, 90), width=1)
        draw.text((3, py + 3), str(y), fill=(0, 110, 255, 235))
        y += step_real


def grab(
    monitor: int = 0,
    region: dict | None = None,
    max_width: int = 1400,
    fmt: str = "jpeg",
    quality: int = 72,
    grid: bool = False,
    grid_step: int = 200,
) -> Shot:
    """Capture one monitor, the whole desktop, or an arbitrary region.

    region is expressed in virtual-desktop coordinates (x/y may be negative).
    """
    with mss.mss() as sct:
        if region:
            box = {
                "left": int(region["x"]),
                "top": int(region["y"]),
                "width": int(region["width"]),
                "height": int(region["height"]),
            }
            if box["width"] <= 0 or box["height"] <= 0:
                raise ValueError("The width and height of the region must be positive.")
            label = f"region {box['width']}x{box['height']} at ({box['left']}, {box['top']})"
        else:
            if monitor < 0 or monitor >= len(sct.monitors):
                raise ValueError(
                    f"Monitor {monitor} does not exist. Valid values: 0 (all) to {len(sct.monitors) - 1}."
                )
            box = sct.monitors[monitor]
            label = "full virtual desktop" if monitor == 0 else f"monitor {monitor}"

        raw = sct.grab(box)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    origin = (box["left"], box["top"])
    real_size = img.size
    scale = 1.0
    if max_width and img.width > max_width:
        scale = max_width / img.width
        img = img.resize((max_width, max(1, int(img.height * scale))), Image.LANCZOS)

    if grid:
        _draw_grid(img, origin, scale, max(20, grid_step))

    buf = io.BytesIO()
    fmt = fmt.lower()
    if fmt in ("jpg", "jpeg"):
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        mime = "jpeg"
    elif fmt == "webp":
        img.save(buf, format="WEBP", quality=quality)
        mime = "webp"
    elif fmt == "png":
        img.save(buf, format="PNG", optimize=True)
        mime = "png"
    else:
        raise ValueError(f"Unknown format: {fmt!r}. Expected: jpeg, png or webp.")

    return Shot(
        png=buf.getvalue(),
        mime=mime,
        origin=origin,
        real_size=real_size,
        sent_size=img.size,
        scale=scale,
        label=label,
    )


def grab_window(hwnd: int, **kwargs) -> Shot:
    rect = winapi.wintypes.RECT()
    winapi.user32.GetWindowRect(hwnd, winapi.ctypes.byref(rect))
    return grab(
        region={
            "x": rect.left,
            "y": rect.top,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top,
        },
        **kwargs,
    )
