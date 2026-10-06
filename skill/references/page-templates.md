# 页型参考（画布 1280 × 720，坐标原点左上）

所有坐标都是 px。以下数字是**可直接抄的成品参数**，改主题只需换色与字号，不用改结构。

> **先判断页型**：本文里的「目录页」「章节页」都是**可选页型**——先判断这份题材需要哪些页；页型清单里没有的页，不要做。
> 本文是**你自己照着摆元素时的页型参考**：坐标 / 字号 / 色值 / 命名都可直接抄进 `api.insert` 的 `element`。

## 0. 先定设计 token

| token | 用途 | 自然柔和（示例） | 极简商务 | 深色科技 |
| --- | --- | --- | --- | --- |
| `bg` | 页面底色 | `#F6F3ED` | `#FFFFFF` | `#0F1720` |
| `ink` | 主文字 | `#2F3E36` | `#111827` | `#E8EEF6` |
| `accent` | 强调色 | `#C97B4A` | `#2563EB` | `#38BDF8` |
| `muted` | 次要文字 | `#6E7A70` | `#6B7280` | `#8B9BB0` |
| `line` | 分隔线 / 描边 | `#E9E2D6` | `#E5E7EB` | `#243040` |
| `card` | 卡片底 | `#FFFFFF` | `#FFFFFF` | `#16202C` |

更多配方见同目录 `design-recipes.md`。

### 字号阶梯（全篇只用这几档）

| 角色 | 字号 | 字重 | 行高 |
| --- | --- | --- | --- |
| 封面主标题 | 60 | 700 | 1.25 |
| 章节页标题 | 48 | 700 | 1.3 |
| 页主标题 | 34 | 700 | 1.3 |
| 大号数字 | 26–30 | 700 | 1 |
| 卡片标题 | 20–22 | 700 | 1.35 |
| 副标题 | 18–19 | 400 | 1.8 |
| 卡片正文 | 14 | 400 | 1.75 |
| 图注 / 标签 / 页脚 | 12–13 | 400–700 | 1.5 |

### 栅格

- 页边距：左右 64，上 52，下 48
- 三列：`x = 64 / 456 / 848`，列宽 `368`，列间距 `24`（64+368+24=456，456+368+24=848，848+368=1216=1280-64 ✓）
- 内容区两行：`y = 156 / 420`，行高 `240`，行间距 `24`
- 正文列宽 328（卡片宽 368 − 左右各 20 内边距）

## 1. 底板装饰层（所有页共用，一次 `all_pages=True` 铺）

| 元素 | type | x, y, w, h | 关键 style / props |
| --- | --- | --- | --- |
| 页背景 | shape | 0, 0, 1280, 720 | `background: bg`，`borderWidth: 0` |
| 页眉细线 | shape | 64, 136, 1152, 1 | `background: line`，`borderWidth: 0`（只内容页用） |
| 页脚署名 | text | 64, 672, 520, 26 | 12px `muted`，文本如「自然观察笔记 / 编辑部 · 2026 秋」 |
| 页码 | text | 1146, 672, 70, 30 | 24px bold，颜色取 `ink` 的浅阶（如 `#D6CFC2`），`textAlign: right` |
| 角落装饰圆 | shape | 20, 140, 480, 480 | `props.shape: "ellipse"`，`background: #EDE4D6`，`borderWidth: 0` |

一次铺满全篇的写法：

```python
from noedit_core import api

api.insert(path, {"type": "shape", "name": "底板-底色",
    "x": 0, "y": 0, "w": 1280, "h": 720, "z": 0,
    "props": {"shape": "rect"},
    "style": {"background": "#F6F3ED", "borderWidth": 0}}, all_pages=True)

api.insert(path, {"type": "text", "name": "底板-页脚",
    "x": 64, "y": 672, "w": 520, "h": 26,
    "props": {"text": "自然观察笔记 / 编辑部 · 2026 秋"},
    "style": {"fontSize": 12, "color": "#6E7A70"}}, all_pages=True)
```

> 注意：`all_pages=True` 只铺到**调用时已存在的所有页**——先把页数建满再铺底板。底板元素在每页都占 z 序，后插的内容元素自然压在它上面（z 递增）。若发现被底板压住，把底板的 `z` 设为 0。

## 2. 封面页

左文右图，图满幅出血到右边与上下边。

| 元素 | type | x, y, w, h | 关键参数 |
| --- | --- | --- | --- |
| 装饰底纹圆 | shape/ellipse | 20, 140, 480, 480 | `background: #EDE4D6`，`borderWidth: 0` |
| 标签底 | shape/rect | 80, 168, 252, 38 | `background: #EAD9C6`，`borderRadius: 19`，`borderWidth: 0` |
| 标签文字 | text | 80, 178, 252, 22 | 13px，`#A9603A`，`textAlign: center`，`letterSpacing: 2`，内容如「NATURE NOTES · 2026」 |
| 主标题 | text | 80, 228, 580, 120 | 60px，700，`ink`，`lineHeight: 1.25` |
| 强调短线 | shape/rect | 80, 362, 64, 5 | `background: accent`，`borderRadius: 3`，`borderWidth: 0` |
| 副标题 | text | 80, 392, 540, 96 | 19px，`muted`，`lineHeight: 1.8` |
| 页脚署名 | text | 80, 616, 520, 26 | 13px，浅灰 |
| 页码 | text | 620, 608, 72, 34 | 26px，700，浅色，`textAlign: right` |
| 主图（或图槽位） | image / shape | 720, 0, 560, 720 | `props.src: "assets/cover.jpg"`，`fit: cover`（槽位则用 rect 浅色块） |

**变体**：图满幅整页（`0,0,1280,720`）+ 左侧压半透明深色块（`background: "rgba(20,30,25,0.55)"`）再放文字，适合气势型封面。

## 3. 目录页

标题区：页主标题 34px `x 64 y 52 w 760 h 50`；副标题 14px `x 64 y 106 w 900 h 26`。

条目公式：第 `i` 行（`i = 0…5`），行首 `y = 176 + i * 76`。

| 元素 | type | x, y, w, h | 关键参数 |
| --- | --- | --- | --- |
| 序号 | text | 64, y+4, 60, 26 | 13px，700，`accent`，如「01」 |
| 条目标题 | text | 128, y, 700, 34 | 22px，700，`ink` |
| 条目说明 | text | 128, y+38, 700, 22 | 13px，`muted`（可省） |
| 页码 | text | 1080, y+4, 136, 26 | 14px，`muted`，`textAlign: right` |
| 分隔线 | shape/rect | 64, y+52, 1152, 1 | `background: line`，`borderWidth: 0` |

条目数超过 6 时改成两列（左列 `x 64`，右列 `x 664`，每列 4 行）。

## 4. 章节页

| 元素 | type | x, y, w, h | 关键参数 |
| --- | --- | --- | --- |
| 整页色块 | shape/rect | 0, 0, 1280, 720 | `background: ink`（深色），`borderWidth: 0` |
| 超大章节号 | text | 80, 170, 320, 200 | 140px，700，颜色取深色底上略亮的同色系（如 `#3E4F45`），只做氛围 |
| 装饰短线 | shape/rect | 80, 400, 64, 5 | `background: accent`，`borderRadius: 3` |
| 章节标题 | text | 80, 428, 800, 76 | 48px，700，用 `bg` 或 `#F6F3ED` |
| 章节描述 | text | 80, 516, 640, 60 | 18px，浅灰如 `#B9C2B8`，`lineHeight: 1.7` |
| 页码 | text | 1120, 648, 96, 30 | 24px，700，浅色，`textAlign: right` |

## 5. 内容页（3 × 2 卡片网格）

标题区同目录页。**六张卡片的底**（循环）：

```
卡1 (64, 156)   卡2 (456, 156)   卡3 (848, 156)
卡4 (64, 420)   卡5 (456, 420)   卡6 (848, 420)
```

卡片底统一：

```json
{"type": "shape", "name": "卡片1-底", "x": 64, "y": 156, "w": 368, "h": 240,
 "props": {"shape": "rect"},
 "style": {"background": "#FFFFFF", "borderColor": "#E9E2D6", "borderRadius": 16,
           "borderWidth": 1, "boxShadow": "0 10px 28px rgba(70,55,40,0.07)"}}
```

卡内 5 件套（以卡片左上角 `(cx, cy)` 为基准）：

| 元素 | type | 相对坐标 | 关键参数 |
| --- | --- | --- | --- |
| 强调竖条 | shape/rect | cx+20, cy+22, 6, 26 | `background: accent`，`borderRadius: 3`，`borderWidth: 0` |
| 编号 | text | cx+38, cy+24, 120, 22 | 13px，700，`accent`，如「01」 |
| 卡标题 | text | cx+20, cy+60, 328, 32 | 20px，700，`ink` |
| 卡正文 | text | cx+20, cy+102, 328, 120 | 14px，`muted`，`lineHeight: 1.75` |

**图片卡**（替换卡内除标题外的部分）：

| 元素 | type | 绝对坐标 | 关键参数 |
| --- | --- | --- | --- |
| 卡图 / 图槽位 | image / shape | cx+14, cy+14, 340, 156 | `fit: cover`，`borderRadius: 10` |
| 图注标题 | text | cx+18, cy+186, 328, 22 | 14px，700，`ink` |
| 图注说明 | text | cx+18, cy+210, 328, 20 | 12px，`muted` |

**图表卡**：

| 元素 | type | 绝对坐标 | 关键参数 |
| --- | --- | --- | --- |
| 卡标题 | text | cx+38, cy+22, 312, 24 | 16px，700，`ink` |
| 图表 | chart | cx+14, cy+58, 340, 164 | `kind: "bar"`，`showLegend: false`，`showValues: true`，`rows: [["山脊",18],["潮汐",26],["星空",14],["瀑布",22],["林间",31]]`，`palette: ["#2F3E36","#7C8B6B","#C97B4A","#A9603A","#D9CDBB"]` |

> 图表是透明背景的内联 SVG（viewBox 640×360）。柱状图**只用 `palette[0]`** 一个颜色，`showLegend` 对 bar 无效。字段细节见同目录 `element-schema.md`。

做多页内容页时：**先把这一页的元素 JSON 定稿，再逐页 `api.insert(element, page_index=N)` 重铺一遍**——核心没有复制页的 API，母版元素要在每一页各自重新插入；铺完再逐页 `api.update` 改文字。

## 6. 致谢页

| 元素 | type | x, y, w, h | 关键参数 |
| --- | --- | --- | --- |
| 页面色块 | shape/rect | 0, 0, 1280, 720 | `background: bg` |
| 装饰圆 | shape/ellipse | 840, 100, 520, 520 | 浅色，`borderWidth: 0` |
| 主文案 | text | 220, 262, 840, 90 | 54px，700，`ink`，`textAlign: center`，如「谢谢观看」 |
| 副文案 | text | 220, 372, 840, 40 | 18px，`muted`，居中 |
| 联系方式 | text | 220, 430, 840, 30 | 14px，`accent`，居中，如「hello@example.com / @yourhandle」 |

## 7. 命名规范

元素 `name` 用可读中文：`卡片3-图注`、`底板-页脚`、`图槽-01`、`封面-主标题`。好处：`match.nameContains` 能一把定位同类元素做统一修改，比记 id 稳。

## 8. 溢出估算与修正

排版前先按字数估宽度，避免导出后返工：

- 中文按「字号 × 字数」估宽。60px 标题、`w 580` → 最多 9 字；34px 标题、`w 760` → 最多 22 字。
- 正文 14px、`w 328` → 每行约 22 字；`h 120`、行高 1.75 → 最多 4 行 = 约 88 字。
- 副标题 19px、`w 540` → 每行约 28 字。
- 超了就：减字 → 降字号一档 → 加宽 → 增大 `h`，按这个顺序改。

核心不做文字溢出检查，交付前导图逐页核对（`api.export(path, "png")`），或按上面的公式逐条自查。
