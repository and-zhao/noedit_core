"""微场景 GIF 合成：逐帧抓到的 dataURL 帧 → 一张动图。

抓帧在浏览器里做（core/scene_capture.py 用无头浏览器逐帧 seek(t) 抓帧），
这里只负责把帧合成为 GIF（Pillow，python-pptx 已依赖它，无新增依赖）。

能不能导出 GIF 取决于容器有没有实现 seek(t)：
没实现 seek 的场景是「自播」的，采样不出确定的时间点，抓帧阶段就会直接拦住
（见 core/scene_capture.py 对「逐帧画面完全相同」的判定）。
"""

from __future__ import annotations

import base64
import binascii
import io
import re
from pathlib import Path

from .export import _resolve_out_dir

MAX_FRAMES = 400
# 帧数据（base64 字符数）总量上限：解码要占内存，超了直接拒绝比崩掉好
MAX_PAYLOAD_CHARS = 80 * 1024 * 1024

# 透明背景用的调色板索引。GIF89a 只支持「一个索引」级别的透明：
# 把量化色数压到 255，索引 255 就空出来专门标记「完全透明」的像素。
TRANSPARENT_INDEX = 255

# 判定"透明"的 alpha 阈值：只有 alpha 低于它的像素才真的切成透明。
# 取一个很小的值（而不是 128）是为了不把光晕 / 抗锯齿的柔边整块切掉。
ALPHA_CUTOFF = 24

_DATA_URL = re.compile(r"^data:image/[a-z0-9.+-]+;base64,", re.I)


def _file_stem(name) -> str:
    text = re.sub(r'[\\/:*?"<>|]+', "_", str(name or "scene")).strip()
    return text or "scene"


def _hex_rgb(text: str, default=(255, 255, 255)):
    t = str(text or "").strip().lstrip("#")
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) != 6:
        return default
    try:
        return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default


def _decode(data_url: str):
    """dataURL（或裸 base64）→ PIL.Image；解不出来返回 None。"""
    from PIL import Image

    text = str(data_url or "").strip()
    if not text:
        return None
    if _DATA_URL.match(text):
        text = _DATA_URL.sub("", text)
    try:
        raw = base64.b64decode(text, validate=False)
    except (binascii.Error, ValueError):
        return None
    if not raw:
        return None
    try:
        return Image.open(io.BytesIO(raw))
    except Exception:  # noqa: BLE001 —— 单帧坏了就跳过，不该拖垮整次导出
        return None


def export_scene_gif(project_root, payload: dict) -> dict:
    """把 payload["frames"]（dataURL 数组）合成为 GIF，落到导出目录。"""
    from PIL import Image

    payload = payload or {}
    raw_frames = [f for f in (payload.get("frames") or []) if isinstance(f, str) and f.strip()]
    if len(raw_frames) < 2:
        return {"ok": False, "path": "", "message": "至少需要 2 帧才能合成动图（当前只有 %d 帧）" % len(raw_frames)}
    if len(raw_frames) > MAX_FRAMES:
        return {
            "ok": False,
            "path": "",
            "message": f"帧数太多（{len(raw_frames)} 帧，上限 {MAX_FRAMES}）：把时长或帧率调小一点再试",
        }
    if sum(len(f) for f in raw_frames) > MAX_PAYLOAD_CHARS:
        return {
            "ok": False,
            "path": "",
            "message": "帧数据太大：把「输出宽度」调小（如 480）或降低帧率后再试",
        }

    fps = max(1, min(60, int(payload.get("fps") or 12)))
    loop = 0 if payload.get("loop", True) is not False else 1
    background = _hex_rgb(payload.get("background"), (255, 255, 255))
    transparent = bool(payload.get("transparent"))

    frames = []
    broken = 0
    for raw in raw_frames:
        image = _decode(raw)
        if image is None:
            broken += 1
            continue
        frames.append(image.convert("RGBA"))
    if len(frames) < 2:
        return {"ok": False, "path": "", "message": "帧数据都解不出来（可能被截断了），请重试"}

    width, height = frames[0].size
    flat = []
    aligned = []
    for image in frames:
        if image.size != (width, height):   # 尺寸不一致的帧统一拉到第一帧的尺寸
            image = image.resize((width, height))
        aligned.append(image)
        # GIF 没有真正的 alpha 混合：先把透明区域铺成底色，否则边缘会发黑
        canvas = Image.new("RGB", (width, height), background)
        canvas.paste(image, (0, 0), image)
        flat.append(canvas)

    # 用若干帧拼一张参考图统一量化：否则 Pillow 会逐帧各自量化，整片画面会来回闪色。
    # 采样点必须**均匀铺满整个时长**：只取前几帧会漏掉后段才大面积出现的颜色。
    sample_count = min(len(flat), 12)
    if sample_count >= len(flat):
        sample = flat
    else:
        step = len(flat) / sample_count
        sample = [flat[min(len(flat) - 1, int(index * step))] for index in range(sample_count)]
    montage = Image.new("RGB", (width, height * len(sample)))
    for index, image in enumerate(sample):
        montage.paste(image, (0, index * height))
    # 透明模式留出一个索引给「完全透明」，所以量化色数要少一个
    colors = TRANSPARENT_INDEX if transparent else 256
    palette = montage.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    # 开抖动：微场景常有光晕 / 渐变 / 发光边框，关掉抖动时 256 色量化误差会在渐变区堆成硬色带。
    gif_frames = []
    for base, source in zip(flat, aligned):
        quantized = base.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
        if transparent:
            # 只有「几乎全透明」的像素才真的切成透明；GIF 只有 1-bit 透明，切掉就是彻底没了。
            mask = source.getchannel("A").point(lambda value: 255 if value < ALPHA_CUTOFF else 0)
            quantized.paste(TRANSPARENT_INDEX, (0, 0, width, height), mask)
            quantized.info["transparency"] = TRANSPARENT_INDEX
        gif_frames.append(quantized)

    target = _resolve_out_dir(Path(project_root), str(payload.get("outDir") or "")) / f"{_file_stem(payload.get('name'))}.gif"
    save_kwargs = {}
    if transparent:
        save_kwargs["transparency"] = TRANSPARENT_INDEX
    try:
        gif_frames[0].save(
            str(target),
            save_all=True,
            append_images=gif_frames[1:],
            duration=max(20, int(round(1000 / fps))),
            loop=loop,
            disposal=2,          # 每帧先清成背景再画，避免残影叠加
            optimize=True,
            **save_kwargs,
        )
    except OSError as exc:
        return {"ok": False, "path": "", "message": f"写入 GIF 失败：{exc}"}

    size = target.stat().st_size
    size_text = f"{size / 1024:.0f} KB" if size >= 1024 else f"{size} B"
    message = (
        f"已导出 GIF（{len(gif_frames)} 帧 · {fps}fps · {width}×{height} · "
        f"{size_text}{' · 透明背景' if transparent else ''}）：{target}"
    )
    if broken:
        message += f"；{broken} 帧数据损坏已跳过"
    return {
        "ok": True,
        "path": str(target),
        "message": message,
        "format": "gif",
        "frames": len(gif_frames),
        "bytes": size,
        "transparent": transparent,
    }
