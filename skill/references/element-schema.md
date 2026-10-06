# 元素字段字典

`insert` 的 `element` 是一个 JSON 对象。结构：

```json
{
  "type": "text",          // 必填
  "x": 80, "y": 60,        // 画布 px，原点左上
  "w": 420, "h": 90,       // 尺寸 px（不给则用类型的默认尺寸）
  "name": "标题",           // 可选，便于 match 定位
  "props": { ... },        // 类型专属内容（见下）
  "style": { ... },        // 通用样式
  "locked": false          // 可选：true = 锁定的元素，写操作会自动跳过（见下）
}
```

> **权威来源**：核心内 `web/element-schema.json` 是唯一真相。运行时用 `api.element_types()` 拿「类型 + 默认尺寸 + modelNote」；
> 需要某个字段的定义 / 默认值 / 可选项时，直接查该 JSON 的 `types.<类型>.sections[].rows[].fields[].path`（如 `props.rows`）。
> 本文是它的实用摘编，若与 JSON 冲突，以 JSON 为准。

## 通用字段（所有类型）

**元素级**（写在 element 顶层）：`x` `y` `w` `h` `z` `rotate` `opacity` `visible` `parentId` `name` `anim`

- `z` 由 `insert` 自动 = 当前页最大 z + 1（后插在上）；一般不用手写。
- `parentId` 用于 `group` 成员归属。

**通用样式**（写在 `style` 里）：

| 字段 | 说明 |
| --- | --- |
| `fontFamily` | 字体名，内置 Windows 常用中英文字体（微软雅黑 / 等线 / 宋体 / Arial / Consolas…），默认 `Microsoft YaHei` |
| `fontSize` | 字号 px（8–300） |
| `color` | 文字色 |
| `fontWeight` | `"300"`–`"900"`（字符串） |
| `lineHeight` | **只写倍数**（0.8–4，如 `1.5`）——写像素值会崩版 |
| `textAlign` | `left` / `center` / `right` / `justify`（**不要两端对齐**） |
| `verticalAlign` | `top`（默认）/ `middle` / `bottom`；**要垂直居中必须显式写 `middle`** |
| `background` | 填充色（**形状填充只认这个字段，写 `fill` 无效**） |
| `borderWidth` / `borderStyle` / `borderColor` / `borderRadius` | 边框；**默认 `borderWidth:0`（无边框）** |
| `letterSpacing` / `fontStyle` / `textIndent` / `paragraphSpacing` / `padding` / `overflow` | 文字细节 |

> ⚠️ `table` / `chart` 无视大部分通用样式（用各自 `props` 里的字号 / 颜色）；它们的 `style` 只控制**元素外框**（边框 / 背景 / 圆角）。图表尤其如此（`commonStyleSkip` 已声明）。

## 锁定元素

元素数据里可带 `locked: true`，语义是「这块已定稿，别动」。**注意：本核心不做强制拦截**——
不会自动跳过被锁定的元素。所以：

- 对 `locked:true` 的元素调 `update` / `delete` / `reorder`，核心**会照改不误**，不会报错、不会跳过。
- 因此这是**你自己要守的纪律**：动手前先看 `locked`（`list_elements(..., full=True)` 能看到），
  批量修改若可能命中锁定元素，先筛掉它们。

## 12 种类型

| type | label | 默认 w×h | 用途 |
| --- | --- | --- | --- |
| `text` | 文本 | 420×90 | 标题、正文、标注、公式、图注 |
| `image` | 图片 | 360×220 | 照片 / 位图（**原理图请用矢量画**） |
| `video` | 视频 | 420×240 | 视频（本地素材） |
| `link` | 链接 | 300×40 | 可点击链接 |
| `table` | 表格 | 520×200 | 数据表 |
| `code` | 代码块 | 520×220 | 带高亮的代码 |
| `chart` | 统计图 | 520×300 | 20 种统计图 |
| `shape` | 形状 | 220×140 | 色块 / 节点 / 预设形状 |
| `path` | 路径 | 220×140 | 自由轮廓 / 波形 / 线稿 |
| `connector` | 连线 | 200×120 | 连两个元素的线 / 箭头 |
| `scene` | 微场景 | 480×270 | 沙箱 `iframe` 跑 `props.code`；**HTML 一定动，PPTX 会动**（核心抓帧合成 GIF 内嵌） |
| `group` | 分组 | 200×120 | 把多个元素成组 |

---

### text

关键 props：`props.text`（文字）、`props.math`（`true` 默认，允许 `$...$` 公式）、`props.runs`（富文本分段）。

**排版规范（来自 modelNote）**：
- 正文 ≥ 14px、轴标 ≥ 12px、图注 ≥ 11px；同类元素字号 / 小数位保持一致。
- 中文正文一行 18–26 字；行高倍数：正文 1.7–1.8、标题 1.25–1.35；标题层级 ≤ 2。
- 西文用无衬线字体；标题写**结论式**（不要「图表 1」）；坐标轴标题必须带量纲 / 单位。
- 公式：只支持有限命令；大括号用 `\big[ \Big[ \bigg[`（**不要指望 `\left` / `\right`**）；不支持 `\newcommand`；未识别命令会渲染成红色波浪线。要原样显示 `$` 就设 `props.math:false`。
- 垂直居中要显式 `style.verticalAlign:"middle"`。

```python
{"type": "text", "x": 80, "y": 60, "w": 900, "h": 80,
 "props": {"text": "2025 季度营收回顾"},
 "style": {"fontSize": 40, "fontWeight": "700", "color": "#1f2937",
           "verticalAlign": "middle"}}
```

### image

关键 props：`props.src`（**工程内相对路径 `assets/xxx.png`**）、`props.fit`（`cover` 默认裁剪填满 / `contain` 完整显示 / **不要用 `fill`（会拉伸变形）**）、`props.filter.*`（亮度 / 对比 / 饱和 / 灰度 / 模糊）、`props.crop*`（四边裁剪比例）、`props.flipH/flipV`、`props.shadowOn` / `props.reflectOn`。

> 原理图 / 机制图 / 波形 / 符号一律用 `shape` / `path` / `connector` / `chart` 画，**不要用位图或 emoji 替代**（会糊、不可印刷）。

### shape

关键 props：`props.shape`（预设名，默认 `rect`；86 个 OOXML 预设：流程图族 / 箭头族 / 星形 / 标注 / 数学符号 / 圆柱 / 立方体…）、`props.fillType`（`solid` / `gradient` / `image`）、`props.fillGradientTo` / `props.fillGradientAngle` / `props.fillOpacity`、`props.strokeDash` / `props.strokeCap` / `props.strokeJoin`、四角独立圆角 `props.radiusTL/TR/BR/BL`、`props.shadowOn` / `props.glowOn` / `props.reflectOn`。

- 填充写 `style.background`；渐变只能靠 `props.fillType:"gradient"`（**不要往 `style.background` 塞 `linear-gradient()`**）。
- **默认无边框**；要框线显式写 `style.borderWidth`(+`style.borderColor`)。
- `props.shape:"line"` 这类只靠描边的形状**必须写 `borderWidth > 0`**，否则不可见。
- 示意图规范：节点 1px 描边、对齐栅格、连线只走正交；**shape 不装文字**（图文分离，文字用同坐标独立 `text`）；每图节点 ≤ 12、连线 ≤ 节点数 × 1.5。

### path

关键 props：`props.d`（SVG path 数据，**坐标是元素局部 0..w / 0..h**）、`props.fillRule`（`nonzero` / `evenodd`）、其余同 shape（fillType / 描边三件套 / 阴影发光倒影）。

- 曲线用多段 `C` 拟合，**避开弧线命令 `A`/`a`**（PPTX 会回退成截图、丢可编辑性）。
- 线稿必须显式写 `style.borderWidth > 0` 才可见。

### connector

关键 props：`props.from` / `props.to`（端点，**至少一端绑到元素**，否则退化成看不见的点）、`props.route`（`straight` / `elbow` / `curve` 默认）、`props.corner`、`props.arrowStartType` / `props.arrowEndType`（`none` / `triangle` 实心三角（末端默认）/ `hollowTriangle` / `open` / `diamond` / `hollowDiamond` / `stealth`）、`props.arrowSize`。

- 端点写法：① 写**目标元素的名字或其文字内容**（如 `"开始框"`，推荐——节点移动后线自己跟着走）；② 写 `{"x": 绝对画布坐标, "y": 绝对画布坐标}` 的自由端点。
- 默认描边 `style.borderWidth:2`（连线靠描边显形，**别设 0**）。
- UML 惯例：继承用 `hollowTriangle`、组合用 `diamond`、聚合用 `hollowDiamond`、依赖用 `open` 配虚线（`props.strokeDash:"dash"`）。
- **插入时 x/y/w/h 不用自己算**，系统按两端位置自动算。
- 别用 `shape` 的直线 / 箭头图形代替连线。

### table

关键 props：`props.rows`（二维数组，**每行等长**）、`props.header`（默认 true）、`props.headerBg`（`#f2f4f7`）/ `props.headerColor`（`#1f2328`）、`props.rowBg`（`#ffffff`）/ `props.altBg`、`props.borderColor` / `props.borderWidth`、`props.zebra`、`props.align` / `props.verticalAlign` / `props.aligns`、`props.columnWidths`、`props.merges`、`props.highlights`（单格高亮）、`props.cellPadding` / `props.fontSize`。

- 科研数据用**三线表**：`props.borders:false` + 只留顶线 / 表头下线 / 底线，`props.rowBg` 设透明。
- 表格**默认不透明白底**——放暗色页会自带一块白底。
- 表身单元格默认不写色、继承 `style.color`；表头默认浅底深字（`headerBg:#f2f4f7` / `headerColor:#1f2328`）。
- **深色底（含黑底）必须显式给浅色 `style.color` + 浅色 `props.headerColor`**；白底只能用深色系。文字颜色要跟**衬底**反差（表身衬底 / 表头底 / 单格 `highlights` 底），不是跟页面底。
- 没有「表题」字段，要表题就在表格上方另起一个 `text`。

### code

关键 props：`props.code`、`props.lang`（**必填**，不给高亮不对）、`props.title` / `props.langLabel`、`props.theme`（`dark` 默认 / `light` / `auto`）、`props.showBar` / `props.macStyle` / `props.lineNumbers` / `props.wrap` / `props.shadow`、`props.startLine` / `props.tabSize` / `props.fontSize` / `props.lineHeight` / `props.padding` / `props.radius`、`props.bgColor` / `props.fgColor` / `props.accent`、`props.highlightLines`。

- **默认深色主题**；放浅色页要显式 `props.theme:"light"`。
- 每段代码必须显式给 `props.lang`，并在旁边用 `text` 说明这段代码做什么。

### chart

关键 props：`props.kind`（图型）、`props.rows`（数据）、`props.seriesNames`、`props.palette` / `props.palettePreset` / `props.heatColors`、坐标轴与字号颜色一大组（见下）。

**20 种 kind**：`bar` 柱状、`hbar` 条形、`line` 折线、`area` 面积、`stackedArea` 堆叠面积、`pie` 饼、`donut` 环形、`rose` 南丁格尔玫瑰、`radar` 雷达、`scatter` 散点、`bubble` 气泡、`funnel` 漏斗、`gauge` 仪表盘、`progress` 进度条、`box` 箱线、`violin` 小提琴、`hist` 直方图、`ecdf` 累积分布、`heatmap` 热力图、`errorbar` 误差棒。

**`props.rows` 语义**（易错，务必对照）：
- 常规图（bar / hbar / line / area / stackedArea / pie / donut / rose / radar / gauge / progress）：**每行一条数据，第一列是类别，后面每列是一个系列**。如 `[["一月", 30], ["二月", 55]]`；多列 = 多系列。
- 统计图形（box / violin / hist / ecdf / errorbar）：**第一列是分组名（同名自动合并成一组），该行其余数值都算这组的样本**，如 `[["A",3.1],["A",3.5],["B",4.2]]`；也可宽表 `[["A",1,2,3]]`。
- 散点 / 气泡：第一列是数值 x，其后是 y；气泡再下一列是尺寸，如 `[[12,46,32]]`。第一列若是文字分组会自动跳过该列。
- 非数值行（如表头）自动忽略。

**选型**：比较→`bar`/`hbar`；趋势→`line`/`area`；构成随时间→`stackedArea`；占比→`pie`/`donut`；层级→`rose`；多指标→`radar`/`heatmap`；相关→`scatter`/`bubble`；分布→`box`/`violin`/`hist`/`ecdf`；流程转化→`funnel`；达成→`gauge`/`progress`；离散度→`errorbar`。

**坐标轴 / 统计层**：`props.zeroBase`（普通柱图设 true 从 0 起）、`props.axisBox`、`props.xTitle` / `props.yTitle`（**必带单位**）、`props.showGrid` / `props.gridCount` / `props.maxValue` / `props.minValue`、`props.errorType`（`none`/`sd`/`sem`/`ci95`）、`props.compare`（显著性比较）、`props.sigCorrect`、`props.fitType`（拟合）+ `props.fitShowEq` / `props.fitShowR2`。

**文字与配色**：`props.title` / `props.titleSize` / `props.titleColor`、`props.fontSize`、`props.labelColor`、`props.valueColor`、`props.gridColor`、`props.axisColor`、`props.showValues` / `props.valueFormat` / `props.valueColor`、`props.showLegend` / `props.legendPos`。

> 放**深色底**时需要显式把上面这组文字 / 轴线颜色一起调成浅色（默认是给浅底用的）。

```python
{"type": "chart", "x": 600, "y": 180, "w": 560, "h": 360,
 "props": {"kind": "bar", "title": "季度营收",
           "rows": [["Q1", 120], ["Q2", 180], ["Q3", 150], ["Q4", 210]],
           "xTitle": "季度", "yTitle": "营收（万元）", "zeroBase": True}}
```

### group

把已有元素成组：新建 `group` 元素后，把成员的 `parentId` 设为该组的 `id`（成员坐标转为相对组）。分组不改变导出结果，只影响编辑与整体移动。

### scene（微场景）

用你写的**前端代码**画动态内容，跑在独立沙箱 `iframe` 里（拿不到主页面 DOM、CSS 不外泄、崩了只影响这个容器）。字段（`props`）：

- `code`：容器内的 JS。可选实现 `mount(container, params)` / `seek(t)` / `unmount()`；实现了 `seek` 就跟随时间轴（`t` 取 `0..duration` 秒）。
- `duration`：表演时长（秒，默认 3）。
- `loop`：是否循环（默认 `true`）。
- `libs`：要用的前端库 id 数组（`p5` / `anime` / `gsap` / `three` / `chart` / `d3` / `matter` / `confetti`）——**该库必须已在本地缓存**，否则场景不跑并提示「缺少本地库」；用 `api.install_scene_lib("gsap")` 下载（**会联网**），`api.scene_libs()` 查看已缓存哪些。
- `poster`：封面帧（静态图，`dataURL` 或 `assets/xxx.png`）。

**关键限制**：

- **HTML 导出一定动**：工程内 `index.html` / `export(path,"html")` 里是真 `iframe` 在跑代码。
- **PPTX 里微场景会动**：核心在导出前用本机 Edge/Chrome **逐帧抓帧、合成 GIF 内嵌**（需容器实现了 `seek(t)`；自播场景抓不出时间点，会判失败并退回封面帧）。想单拿 GIF：`api.export_scene_gif(path, match={"name": "..."})`。
- **PDF / PNG / SVG 是静态的**：微场景只画 `props.poster`，没有 `poster` 就用深色占位图。
- 核心**不生成** `code` / `poster`——代码你自己写，封面帧你得自己备好（GIF 由核心抓帧生成）。

```json
{"type": "scene", "x": 80, "y": 80, "w": 480, "h": 270,
 "props": {"duration": 3, "loop": true,
           "code": "window.mount=function(c){c.innerHTML='<b>Hello</b>';};"}}
```

## 页面背景

页面背景写在 `page.background`，结构同画布背景：

```json
{"type": "solid", "color": "#ffffff", "image": "", "fit": "cover"}
```

- `type` = `solid`（纯色，用 `color`）或 `image`（用工程内素材相对路径 `image`，`fit` 建议 `cover`）。
- 新建页 / 加页时通过 `add_page(..., background={...})` 传入（会与页面默认背景合并）。
- 全篇统一背景：建页时逐页给同一份 `background`，**不要**用满幅 `image` 元素当背景。
