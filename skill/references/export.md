# 导出

```python
api.export(path, fmt="pptx", out_dir="", **options)
```

`fmt ∈ html | pdf | pptx | png | svg`。默认落到**工程内的 `export/` 目录**（`<工程>/export/`），`out_dir` 可指定其它目录。
文件名默认取工程名；同名文件已存在时自动加 ` (2)` / ` (3)`，**不会覆盖上一次导出**。

返回统一结构：`{"ok", "path", "message", "format"}`；`png` / `svg` 额外带 `paths`（多页路径列表）与 `warnings`。
`ok=False` 时 `path` 为空、`message` 说明原因。

| fmt | 产物 | 运行期依赖 |
| --- | --- | --- |
| `html` | 静态画布 HTML（多页，可离线打开） | 无（render-kit 已内联） |
| `pptx` | PowerPoint（矢量优先，可继续编辑） | **python-pptx** |
| `pdf` | PDF | 本机 **Edge / Chrome**（无头打印） |
| `png` | 逐页 PNG（可选透明 / 高 DPI） | 本机 **Edge / Chrome**（无头截图） |
| `svg` | 逐页矢量 SVG | 本机 **Edge / Chrome** |

---

## html

- **自包含**：渲染脚本（render-kit / tokens）已内联进 HTML，不需要 `web/` 目录。
- **但图片素材仍按相对路径引用**：导出到 `<工程>/export/` 时，HTML 用 `../assets/xxx` 指回工程素材。
  所以这份 HTML **要和工程文件夹一起搬**；单拎出来会丢图。
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

## 导出前

不需要额外「保存」：`insert` / `update` / `delete` 都已即时写盘并刷新工程 `index.html`，导出读的就是最新状态。
但**写操作要串行**（有跨进程文件锁），不要并发导出与写入同一工程。
