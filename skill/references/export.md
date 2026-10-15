# 导出

```python
api.export(path, fmt="pptx", out_dir="", **options)
```

`fmt ∈ html | pdf | pptx | png | svg | video`。默认落到**工程内的 `export/` 目录**（`<工程>/export/`），`out_dir` 可指定其它目录。
文件名默认取工程名；同名文件已存在时自动加 ` (2)` / ` (3)`，**不会覆盖上一次导出**。

返回统一结构：`{"ok", "path", "message", "format"}`；`html` / `png` / `svg` / `video` 额外带 `warnings`（`png` / `svg` 还带 `paths` 多页路径列表）。
`ok=False` 时 `path` 为空、`message` 说明原因。**`warnings` 非空要如实转达用户**，别当没有。

| fmt | 产物 | 运行期依赖 |
| --- | --- | --- |
| `html` | 静态画布 HTML（多页，可离线打开） | 无（render-kit 已内联） |
| `pptx` | PowerPoint（矢量优先，可继续编辑） | **python-pptx** |
| `pdf` | PDF | 本机 **Edge / Chrome**（无头打印） |
| `png` | 逐页 PNG（可选透明 / 高 DPI） | 本机 **Edge / Chrome**（无头截图） |
| `svg` | 逐页矢量 SVG | 本机 **Edge / Chrome** |
| `video` | 一条带旁白与烧制字幕的 mp4（科普视频成片） | 本机 **Edge / Chrome** + **ffmpeg**（含 libass、libx264；`pip install imageio-ffmpeg` 即可） |

---

## html

- **自包含**：渲染脚本（render-kit / tokens）已内联进 HTML，不需要 `web/` 目录。
- **但图片 / 音频 / 视频素材仍按相对路径引用**：导出到 `<工程>/export/` 时，HTML 用 `../assets/xxx` 指回工程素材。
  所以这份 HTML **要和工程文件夹一起搬**；单拎出来会丢图、丢旁白、丢数字人。
- `out_dir` 落在**工程目录之外**时，返回的 `warnings` 会点名这条（前缀是 `../<工程>/`）；
  要「单文件发出去就能放」就导 **PPTX**（图片 / 音频 / 视频 / 场景 GIF 全部内嵌）。
- 是「交付真相」——所有页面都是真 HTML/CSS，浏览器里所见即最终效果，也是本地预览的首选。

---

## pptx

- 导出策略**矢量优先**：纯文字 / 图片 / 图形 / 连线 / 原生图表 / 原生表格 / 代码 / 公式直接写成可编辑矢量；
  碰上**渐变 / 投影 / 发光 / 元素级不透明度（`opacity` / `fillOpacity`）/ 模糊 / 弧线路径**等矢量保不住的效果，该元素自动回退成截图。
  颜色字符串自带的 `rgba()` alpha 不在此列：会原生写成 `a:alpha`，保矢量且与画布一致。
  单元素也可用 `props.rasterMode: "raster"`（稳截图）强制贴图——观感 100% 与画布一致但不可编辑。
- 缺 python-pptx 时返回 `ok=False`，`message` 提示安装（`pip install python-pptx`）。
- `scene`（微场景）在 PPTX 里**会动**：核心导出前用本机 Edge/Chrome 逐帧 `seek(t)` 抓帧 → Pillow 合成 GIF → 内嵌进幻灯片（需容器实现 `seek(t)`；抓帧失败或没装浏览器时退回 `props.poster` 封面帧）。
  给 `scene_gifs=False` 可关掉自动抓帧（只留封面帧）；也可直接传 `{元素id: GIF路径}` 用现成的动图。
- 元素 `anim`（动画）**只在 HTML 导出会播放**；PPTX / PDF / PNG / SVG 停在静态帧。

---

## pdf / png / svg（需浏览器）

三者都靠本机 **Edge 或 Chrome** 的无头模式渲染工程 HTML。找不到浏览器时 `ok=False` 并提示。

- 浏览器探测顺序：环境变量 → 常见安装路径；不在标准位置时导出会失败。
- **png / svg 专属 options**：

| option | 说明 |
| --- | --- |
| `pages` | `"1"` / `"1,3"` / `"2-5"`；空 = 全部页 |
| `dpi` | `96` / `150` / `300`（默认）/ `600` |
| `transparent` | `True` 时 PNG 不要页面背景（拿透明通道） |

- `transparent=True` 但当前浏览器截图拿不到透明通道时，会**自动铺白底**并在 `warnings` 里说明。
- 返回 `paths` 是逐页文件路径列表（`path` 是第一页）。

```python
api.export(path, "png", pages="1,3", dpi=300, transparent=True)
api.export(path, "svg", pages="")          # 全部页
```

---

## video（mp4 成片，需 ffmpeg）

把一份 deck 变成**会自己讲、带烧制字幕**的 mp4：AI 写完稿 + 旁白，就能直接出一条科普视频。

```python
res = api.export(path, "video")                       # 全 14 页，约 15~20 分钟
res = api.export(path, "video", captions=False)       # 不要字幕
res = api.export(path, "video", width=1280, preset="ultrafast")   # 快糙预览
```
命令行：`python main.py export <工程目录> --fmt video [--fps 25] [--width 1920] [--tail 0.8] [--min-seconds 4] [--keep-segments]`

**做法与取舍**（逐页合成再拼接，不逐帧抓动画）：
每页一张 300 DPI 静帧 → ffmpeg 缓推运镜（Ken Burns）→ 按 `props.captions` 烧 ASS 字幕
→ 该页 audio / 数字人音轨按 `startAt` 摆位混音 → 逐页编成**参数完全一致**的分段 → `concat -c copy` 无损拼接。
不逐帧抓动画是因为：14 页 × 30 秒 × 25 帧 = 一万次无头 `seek()`，代价与收益完全不成比例；
「画面会动」这件事 PPTX 的场景 GIF 已经解决，mp4 这条线的价值是**讲稿 + 配音 + 字幕一次到位**。

- **字幕文本只认 `props.captions`**：给每条 `audio` / `digital_human` 元素填上它念的原文，
  没填的页会在 `warnings` 里点名「这页不出字幕」。断条规则：句末标点切 → 超 22 字再按逗号断 →
  按字数把音频时长摊给各句（TTS 给不了逐句时间戳，这个精度观众看不出）。
- **页时长 = 该页最长的非循环音轨 + `tail`**；`loop=True` 的背景乐不驱动页长。
  没有旁白的页停 `min_seconds` 秒（默认 4）并出一条 warning——成片能放，但那几页是哑的。
- **数字人页不运镜**：静帧当底图，把它的 mp4 按元素坐标叠在画面上（画布 1280×720 → 输出 1920×1080 等比 ×1.5），
  声音直接用这条视频的音轨。运镜会让叠层与版面错位，所以这类页画面是定住的。
- 画面层会**剥掉 `audio` / `digital_human` 元素本身**（播放控件不该出现在成片里），其余元素照常。
- `scene`（微场景）在视频里是**静帧**（浏览器截到的那一帧），不会动。
- **只出整份 deck**：传 `pages` 直接 `ok=False` 说明，不会悄悄漏页。要单页画面导 `fmt="png"`。
- 依赖缺失一律 `ok=False` + 明确原因（没 ffmpeg / 没浏览器 / 某页静帧失败 / 某页合成失败），
  **绝不出一个静音黑屏的 mp4**。成片还会做一次体检：时长与预期比对（偏差超 5% 报 warning）+ 抽帧看亮度（接近全黑报 warning）。

| option | 默认 | 说明 |
| --- | --- | --- |
| `fps` | `25` | 帧率 |
| `width` | `1920` | 输出宽（高按画布比例算，1280×720 → 1080） |
| `dpi` | `300` | 静帧 DPI，预览时可降到 150 |
| `tail` | `0.8` | 旁白念完后每页再停的秒数 |
| `min_seconds` | `4.0` | 无旁白页的停留秒数 |
| `captions` | `True` | 传 `False` 整体关掉字幕 |
| `font` / `font_size` | `Microsoft YaHei` / 高的 1/20 | 字幕样式 |
| `page_seconds` | 无 | 强制页长：一个数，或逐页的列表（想卡固定节奏时用） |
| `preset` / `crf` | `veryfast` / `21` | x264 参数 |
| `keep_segments` | `False` | `True` 时把逐页分段 mp4 也复制到导出目录（排查哪页坏了） |
| `timeout` | `1800` | 单页编码上限（秒） |

返回除通用字段外还有：`duration` / `fps` / `width` / `height`，以及逐页表
`pages: [{"page", "seconds", "tracks", "cues"}]`——**汇报成片时把这张表转给用户**，哪页几秒、几条音轨、几条字幕一目了然。

---

## 导出前

不需要额外「保存」：`insert` / `update` / `delete` 都已即时写盘并刷新工程 `index.html`，导出读的就是最新状态。
但**写操作要串行**（有跨进程文件锁），不要并发导出与写入同一工程。
