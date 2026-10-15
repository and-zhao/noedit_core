"""视频导出（fmt="video"）：把一份 deck 变成会自己讲、带字幕的 mp4。

做法（刻意不逐帧抓动画，见 skill/references/export.md 的取舍说明）：
  每页一张高 DPI 静帧 → ffmpeg 缓推运镜（Ken Burns）→ 按 props.captions 烧 ASS 字幕
  → 该页音频 / 数字人音轨按 startAt 摆位混音 → 逐页编成参数一致的分段 → concat 无损拼接。
有数字人的页面**关掉运镜**并把它的 mp4 按元素坐标叠在画面上，保证叠层与版面严丝合缝。

依赖：本机 Edge/Chrome（静帧）+ ffmpeg（含 libass、libx264；imageio-ffmpeg 的静态构建即可）。
任一缺失都直接 ok=False 说明原因，绝不出一个静音黑屏的 mp4。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .export import _find_browser, _resolve_out_dir, _safe_name, _unique_path, export_png
from .projects import normalize_manifest

ASS_HEAD = (
    "[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
    "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
    "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H000B0B14,&H96000000,1,0,0,0,100,100,0,0,1,3,1,2,80,80,70,1\n\n"
    "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)
_SENT = re.compile(r"(?<=[。！？；!?;])")
_CUE_MAX = 22          # 一行字幕的上限字数，超了按次级标点再断
_MIN_CUE = 0.9         # 单条字幕最短停留秒数


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _hms(sec: float) -> str:
    """ASS 的时间戳是 h:mm:ss.cc —— 小数点后是**百分秒**。写 3 位会被 libass 当成
    「812 = 8.12 秒」，整条字幕表会往后滑、互相叠在一起（踩过一次，务必保持两位）。"""
    cs = max(0, int(round(float(sec) * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return "%d:%02d:%02d.%02d" % (h, m, s, c)


def _split_cues(text: str) -> list:
    """讲稿 → 字幕条：先按句末标点切，长句再按逗号 / 顿号断到 ≤ _CUE_MAX 字。"""
    out = []
    for raw in (p for p in _SENT.split(str(text or "")) if p.strip()):
        piece = raw.strip().rstrip("。！？；!?;")
        while len(piece) > _CUE_MAX:
            cut = max(piece.rfind("，", 0, _CUE_MAX + 1), piece.rfind("、", 0, _CUE_MAX + 1),
                      piece.rfind(":", 0, _CUE_MAX + 1), _CUE_MAX - 2)
            out.append(piece[:cut].strip("，、: "))
            piece = piece[cut:].lstrip("，、: ")
        if piece:
            out.append(piece)
    return [c for c in out if c]


def _timed_cues(captions: str, start: float, seconds: float) -> list:
    """按字数把该条音频的时长摊给各句（TTS 给不了逐句时间戳，这个精度观众看不出）。"""
    cues = _split_cues(captions)
    if not cues or seconds <= 0:
        return []
    weights = [max(len(c), 1) for c in cues]
    span = max(seconds - 0.3, _MIN_CUE * len(cues))
    scale = span / sum(weights)
    out, t = [], start + 0.15
    for cue, w in zip(cues, weights):
        dur = max(w * scale, _MIN_CUE)
        out.append((t, t + dur * 0.95, cue))
        t += dur
    return out


def _write_ass(path: str, timed: list, width: int, height: int, font: str, size: int) -> None:
    body = "".join("Dialogue: 0,%s,%s,Default,,0,0,0,,%s\n" % (_hms(a), _hms(b), t.replace("\n", " "))
                   for a, b, t in timed)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(ASS_HEAD.format(w=width, h=height, font=font, size=size) + body)


def _is_rel(src) -> str:
    s = str(src or "").strip().replace("\\", "/")
    if not s or s.startswith(("http://", "https://", "data:", "file:")):
        return ""
    return s


def _page_tracks(page: dict, page_no: int, root: Path, ff: str, probe, warnings: list) -> list:
    """收集本页的音轨 / 数字人：算出各自的开始秒、有效时长、字幕、剪辑区间。"""
    tracks = []
    for el in page.get("elements") or []:
        etype = el.get("type")
        if etype not in ("audio", "digital_human"):
            continue
        props = el.get("props") or {}
        rel = _is_rel(props.get("src"))
        name = str(el.get("name") or etype)
        if not rel:
            warnings.append("第 %d 页「%s」的 src 不是工程内素材，视频里已跳过" % (page_no, name))
            continue
        fp = os.path.join(str(root), rel.replace("/", os.sep))
        if not os.path.isfile(fp):
            warnings.append("第 %d 页「%s」素材文件不存在，视频里已跳过：%s" % (page_no, name, rel))
            continue
        start = max(0.0, _num(props.get("startAt")))
        clip_s = max(0.0, _num(props.get("startTime"))) if etype == "digital_human" else 0.0
        clip_e = _num(props.get("endTime")) if etype == "digital_human" else 0.0
        total = _num(probe(fp, ff))
        if total <= 0:
            warnings.append("第 %d 页「%s」读不到时长（文件坏了？），视频里已跳过" % (page_no, name))
            continue
        if clip_e > clip_s:
            dur = min(clip_e - clip_s, max(total - clip_s, 0.0))
        else:
            dur = max(total - clip_s, 0.0)
        tracks.append({
            "kind": etype, "path": fp, "start": start, "seconds": dur, "clip_start": clip_s,
            "volume": 1.0 if props.get("volume") is None else max(0.0, _num(props.get("volume"), 1.0)),
            "loop": bool(props.get("loop")), "captions": str(props.get("captions") or "").strip(),
            "box": el.get("box") or {"x": _num(el.get("x")), "y": _num(el.get("y")),
                                      "w": _num(el.get("w")), "h": _num(el.get("h"))},
            "name": name,
        })
    return tracks


def _filter_graph(tracks: list, width: int, height: int, fps: int, ass_name: str, zoom: bool) -> str:
    """一页的 filter_complex。zoom=True 走缓推运镜；有数字人时不运镜，改按坐标叠视频。"""
    dh = [t for t in tracks if t["kind"] == "digital_human"]
    ass = ("ass=%s" % ass_name) if ass_name else ""
    if not dh:
        if zoom:
            # 静帧先放大到 1.25 倍余量，zoompan 再从中裁 1.0→1.12，避免放大时糊
            sw, sh = int(width * 1.25) & ~1, int(height * 1.25) & ~1
            base = ("[0:v]scale=%d:%d:flags=lanczos,"
                    "zoompan=z='min(zoom+0.0005,1.12)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                    ":s=%dx%d:fps=%d" % (sw, sh, width, height, fps))
        else:
            base = "[0:v]scale=%d:%d:flags=lanczos,setsar=1" % (width, height)
        return base + ("," + ass if ass else "") + ",format=yuv420p[vout]"

    # 有数字人：静帧只做等比放大当底图，逐条把它的 mp4 按画布坐标叠上去（不运镜，否则叠层会漂）
    sx, sy = width / 1280.0, height / 720.0
    segs = ["[0:v]scale=%d:%d:flags=lanczos,setsar=1[bg]" % (width, height)]
    label = "[bg]"
    for k, t in enumerate(dh):
        n = 1 + tracks.index(t)
        ow = max(2, int(round(t["box"]["w"] * sx))) & ~1
        oh = max(2, int(round(t["box"]["h"] * sy))) & ~1
        ox = max(0, min(int(round(t["box"]["x"] * sx)), width - ow))
        oy = max(0, min(int(round(t["box"]["y"] * sy)), height - oh))
        clip = ("trim=start=%g:end=%g," % (t["clip_start"], t["clip_start"] + t["seconds"])
                if (t["clip_start"] or t["seconds"]) else "")
        segs.append("[%d:v]%ssetpts=PTS-STARTPTS+%g/TB,scale=%d:%d:flags=lanczos,setsar=1[dhv%d]"
                     % (n, clip, t["start"], ow, oh, k))
        segs.append("%s[dhv%d]overlay=x=%d:y=%d:eof_action=pass:enable='between(t,%g,%g)'[bg%d]"
                     % (label, k, ox, oy, t["start"], t["start"] + t["seconds"], k))
        label = "[bg%d]" % k
    segs.append("%s%sformat=yuv420p[vout]" % (label, ass + "," if ass else ""))
    return ";".join(segs)


def _audio_graph(tracks: list) -> str:
    """各轨按 startAt 延迟后混音；单轨时省掉 amix。循环音轨（背景乐）不驱动页时长。"""
    if not tracks:
        return ""
    parts, labels = [], []
    for k, t in enumerate(tracks):
        n = 1 + tracks.index(t)
        ms = int(round(t["start"] * 1000))
        head = "[%d:a]" % n
        if t["kind"] == "digital_human" and (t["clip_start"] or t["seconds"]):
            head += ("atrim=start=%g:end=%g,asetpts=PTS-STARTPTS,"
                     % (t["clip_start"], t["clip_start"] + t["seconds"]))
        parts.append("%svolume=%g,adelay=%d|%d[a%d]" % (head, t["volume"], ms, ms, k))
        labels.append("[a%d]" % k)
    joined = "".join(labels)
    # apad：音轨念完到页尾之间补静音，让每段的音视频一样长，concat -c copy 才不会错位
    tail = "alimiter=limit=0.95,apad,aresample=48000[aout]"
    if len(labels) == 1:
        parts.append("%s%s" % (joined, tail))
    else:
        parts.append("%samix=inputs=%d:duration=longest:normalize=0,%s" % (joined, len(labels), tail))
    return ";".join(parts)


def export_video(project_path: str, manifest: dict, out_dir: str = "", options: dict | None = None) -> dict:
    """逐页合成再拼接，返回 {ok, path, message, format, duration, fps, width, height, pages, warnings}。"""
    opts = options or {}
    if opts.get("pages"):
        return {"ok": False, "path": "", "format": "video", "warnings": [],
                "message": "视频导出只出整份 deck（逐页拼成一条时间线，不支持 pages 选页）；"
                            "要单页画面请导 fmt=\"png\"。"}
    root = Path(project_path)
    manifest = normalize_manifest(manifest)
    pages = manifest.get("pages") or []
    if not pages:
        return {"ok": False, "path": "", "message": "工程里没有页面。", "format": "video", "warnings": []}

    from .paths import ensure_dir
    try:
        from ..dh.media import ffmpeg_exe, probe_seconds
    except Exception as exc:  # noqa: BLE001  dh 是可选模块
        return {"ok": False, "path": "", "format": "video",
                "message": "视频导出需要 dh.media（ffmpeg 通道）：导入失败 %s" % exc, "warnings": []}
    ff = ffmpeg_exe()
    if not ff:
        return {"ok": False, "path": "", "format": "video",
                "message": "没找到 ffmpeg：装系统 ffmpeg 或 pip install imageio-ffmpeg 后重试。",
                "warnings": []}
    browser = _find_browser()
    if not browser:
        return {"ok": False, "path": "", "format": "video",
                "message": "没找到 Edge / Chrome，无法给页面截静帧。装 Edge 后重试，或导出 HTML 自己录。",
                "warnings": []}

    fps = max(8, int(_num(opts.get("fps"), 25)))
    tail = max(0.2, _num(opts.get("tail"), 0.8))
    min_seconds = max(1.0, _num(opts.get("min_seconds"), 4.0))
    dpi = int(opts.get("dpi") or 300)
    want_w = int(_num(opts.get("width"), 1920)) & ~1
    canvas = manifest.get("canvas") or {}
    cw = max(1.0, _num(canvas.get("width"), 1280))
    ch = max(1.0, _num(canvas.get("height"), 720))
    out_h = max(2, int(round(want_w * ch / cw))) & ~1
    font = str(opts.get("font") or "Microsoft YaHei")
    font_size = int(_num(opts.get("font_size"), round(out_h / 20)))
    captions_on = opts.get("captions") is not False
    fixed = opts.get("page_seconds")
    keep_segments = bool(opts.get("keep_segments"))
    warnings: list = []

    # 1) 逐页排时间线：页时长由该页最长的「非循环」音轨决定
    plan = []
    for index, page in enumerate(pages):
        page = dict(page, index=index + 1)
        tracks = _page_tracks(page, index + 1, root, ff, probe_seconds, warnings)
        driving = [t for t in tracks if not t["loop"]]
        if isinstance(fixed, (list, tuple)):
            seconds = max(0.5, _num(fixed[index] if index < len(fixed) else None, min_seconds))
        elif fixed is not None:
            seconds = max(0.5, _num(fixed, min_seconds))
        elif driving:
            seconds = max(t["start"] + t["seconds"] for t in driving) + tail
        else:
            seconds = min_seconds
            warnings.append("第 %d 页没有旁白 / 数字人，按 %.1f 秒静帧" % (index + 1, seconds))
        if not captions_on:
            for t in tracks:
                t["captions"] = ""
        elif tracks and not any(t["captions"] for t in tracks):
            warnings.append("第 %d 页没有填 props.captions，成片里这页不出字幕" % (index + 1))
        plan.append({"page": index + 1, "seconds": round(seconds, 3), "tracks": tracks,
                     "name": str(page.get("name") or "")})

    target_dir = _resolve_out_dir(root, out_dir)
    ensure_dir(target_dir)
    work = Path(tempfile.mkdtemp(prefix="noedit_core-video-"))
    seg_paths, rows = [], []
    try:
        # 2) 静帧：画面层剥掉 audio / digital_human（控件不该出现在成片里），数字人另作叠层
        from copy import deepcopy
        still_manifest = deepcopy(manifest)
        for page in still_manifest.get("pages") or []:
            page["elements"] = [el for el in (page.get("elements") or [])
                                if el.get("type") not in ("audio", "digital_human")]
        for item in plan:
            got = export_png(str(root), still_manifest, str(work),
                             {"pages": str(item["page"]), "dpi": dpi})
            if not got.get("ok"):
                return {"ok": False, "path": "", "format": "video", "warnings": warnings,
                        "message": "第 %d 页静帧失败：%s" % (item["page"], got.get("message"))}
            still = got["paths"][0]
            timed = []
            for t in item["tracks"]:
                timed += _timed_cues(t["captions"], t["start"], t["seconds"])
            ass_name = ""
            if timed:
                ass_name = "sub-%02d.ass" % item["page"]
                _write_ass(str(work / ass_name), sorted(timed), want_w, out_h, font, font_size)
            seg = "seg-%02d.mp4" % item["page"]
            cmd = [ff, "-y", "-framerate", str(fps), "-loop", "1", "-i", still]
            for t in item["tracks"]:
                cmd += ["-i", t["path"]]
            graph = _filter_graph(item["tracks"], want_w, out_h, fps, ass_name,
                                  zoom=not any(t["kind"] == "digital_human" for t in item["tracks"]))
            agraph = _audio_graph(item["tracks"])
            silent = not agraph
            if silent:      # 整页无声：补一条静音轨，保证各段流布局一致，concat 才能 -c copy
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            # 输入必须全部在输出选项之前声明完，-map 才能留在后面
            cmd += ["-filter_complex", graph + (";" + agraph if agraph else ""),
                    "-map", "[vout]", "-map", "1:a" if silent else "[aout]"]
            cmd += ["-t", "%.3f" % item["seconds"], "-r", str(fps),
                    "-c:v", "libx264", "-preset", str(opts.get("preset") or "veryfast"),
                    "-crf", str(int(_num(opts.get("crf"), 21))), "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "160k",
                    "-movflags", "+faststart", str(work / seg)]
            r = subprocess.run(cmd, cwd=str(work), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=int(opts.get("timeout") or 1800))
            if r.returncode != 0 or not os.path.isfile(work / seg):
                return {"ok": False, "path": "", "format": "video", "warnings": warnings,
                        "message": "第 %d 页合成失败：%s" % (item["page"], (r.stderr or "")[-600:])}
            seg_paths.append(str(work / seg))
            rows.append({"page": item["page"], "seconds": item["seconds"],
                         "tracks": len(item["tracks"]), "cues": len(timed)})

        # 3) 拼接：各段编码参数完全一致，直接 -c copy 不二次损失
        target = _unique_path(target_dir / ("%s.mp4" % _safe_name(manifest)))
        listf = work / "list.txt"
        listf.write_text("".join("file '%s'\n" % os.path.basename(p) for p in seg_paths),
                         encoding="utf-8")
        out = str(target)
        r = subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", listf.name,
                            "-c", "copy", "-movflags", "+faststart", out],
                           cwd=str(work), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        if r.returncode != 0 or not os.path.isfile(out):
            return {"ok": False, "path": "", "format": "video", "warnings": warnings,
                    "message": "拼接失败：%s" % (r.stderr or "")[-600:]}

        # 4) 产物体检：时长对得上、抽帧不是全黑——静默出一个坏文件是这类功能最坏的失败
        expect = sum(r0["seconds"] for r0 in rows)
        got_sec = _num(probe_seconds(out, ff))
        if got_sec <= 0:
            return {"ok": False, "path": out, "format": "video", "warnings": warnings,
                    "message": "成片读不到时长，可能没真正写出来。"}
        if abs(got_sec - expect) > max(2.0, expect * 0.05):
            warnings.append("成片时长 %.1fs 与预期 %.1fs 偏差较大，请抽查" % (got_sec, expect))
        try:
            from PIL import Image, ImageStat
            dark = 0
            for row, seg_file in list(zip(rows, seg_paths))[:6]:
                at = row["seconds"] / 2
                probe = work / "probe.png"
                subprocess.run([ff, "-y", "-ss", "%.2f" % at, "-i", seg_file,
                                "-frames:v", "1", probe.name], cwd=str(work),
                               capture_output=True, timeout=120)
                if probe.exists():
                    with Image.open(probe) as im:
                        if ImageStat.Stat(im.convert("L")).mean[0] <= 8:
                            dark += 1
            if dark:
                warnings.append("抽到 %d 张接近全黑的帧，请人工复核画面" % dark)
        except Exception:  # noqa: BLE001  没装 Pillow 就不做亮度体检，不影响出片
            pass

        message = "已导出视频（%d 页 / %.1f 秒 / %dx%d@%dfps）：%s" % (
            len(rows), got_sec, want_w, out_h, fps, out)
        if warnings:
            message += "；" + "；".join(warnings[:4]) + ("…" if len(warnings) > 4 else "")
        return {"ok": True, "path": out, "message": message, "format": "video",
                "duration": round(got_sec, 3), "fps": fps, "width": want_w, "height": out_h,
                "pages": rows, "warnings": warnings, "segments": seg_paths if keep_segments else []}
    finally:
        if keep_segments:
            for p in seg_paths:      # 分段留在原临时目录会被系统回收，用户要就搬到导出目录
                dst = os.path.join(str(target_dir), os.path.basename(p))
                try:
                    shutil.copyfile(p, dst)
                except OSError:
                    pass
        shutil.rmtree(work, ignore_errors=True)
