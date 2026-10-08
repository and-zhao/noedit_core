# 图片插入工作流（搜图 / 生图 → 落入工程 → 插入页面）

本文件给**自带 `image_search` / `image_generation` 工具的 Agent** 用：明确什么时候该配图、怎么调用工具、怎么把结果安全地落进 NoEdit Core 工程。

## 核心约束

1. **`props.src` 只能写工程内 `assets/` 的相对路径**（如 `assets/xxx.jpg`）。**不许写 http(s) 外链**——导出件必须离线自包含。
2. **照片感配图才能用搜图/生图**；结构图 / 原理图 / 流程图 / 装置图 / 数据图**必须用矢量**（`shape` / `path` / `connector` / `chart` / 图标库）。
3. **生图/搜图出来的图不得带文字/数字/水印/截图边框**——有文字就用 `text` 元素叠上去。
4. 图片风格必须贴全篇 **6 色 token**，不要出现体系外颜色。

## 什么时候必须主动用搜图 / 生图

在阶段 0（侦察 + 材料就绪）列出每页配图需求，只要满足以下任一条件，**且环境提供了对应工具，就必须主动调用**：

- 封面需要主视觉 / 氛围图；
- 内容页需要真实场景、产品外观、人物、材质、风景等「照片感」内容；
- 用户明确说「配张图」但还没给图；
- 当前工程 `assets/` 为空，而设计需要非矢量视觉元素。

不要等用户催。没有工具或工具失败时，**立即退回图槽位**。

## 标准动作（六步）

### 1. 判断配图位置与数量

| 页面类型 | 建议 | 说明 |
| --- | --- | --- |
| 封面 | **1 张主视觉** | 可满幅，常作页面背景 |
| 章节过渡页 | 0–1 张氛围图 | 可有可无，优先用矢量装饰 |
| 数据 / 流程 / 原理页 | **不配照片** | 用矢量图讲清楚 |
| 产品介绍 / 团队 / 案例页 | 1 张产品 / 团队照片 | 搜图或用户供图 |
| 结尾致谢页 | 0–1 张氛围图 | 小尺寸装饰即可 |

**一页最多 1 张主图**，避免照片喧宾夺主。

### 2. 搜图（优先尝试）

调用工具：`image_search`

关键词公式：

```
主体 + 场景 + 风格 + 色调 + 质量词 + "no text"
```

示例：

```
industrial robotic arm factory floor, cinematic lighting,
clean background, dark blue and orange accents, high quality, no text
```

拿到结果后**逐张检查**：
- 无水印、无截图边框、无奇怪留白；
- 没有乱码文字、数字、字母；
- 色调贴合 6 色 token；
- 商用 / 对外交付时注意版权。

### 3. 生图（搜不到或需特定氛围时用）

调用工具：`image_generation`

提示词公式：

```
主体描述 + 风格词 + 色调词 + 质量词 + 负面词
```

示例：

```
A futuristic industrial robotic arm working on a factory floor,
cinematic, clean, minimalist, professional, high quality,
dark blue and orange accents, soft lighting, no text, no letters,
no numbers, no watermark, no UI elements, no screenshot borders
```

### 4. 落入工程

#### 拿到文件路径

```python
rec = api.import_asset(path, [r"D:\pics\cover_bg.png"])["imported"][0]
print(rec)
# {"name":"cover_bg.png","relPath":"assets/cover_bg.png", ...}
```

#### 拿到 dataURL / URL / 字节

通过 UI 通道上传（POST `/api/call`）：

```json
{
  "method": "upload_asset",
  "args": ["cover_bg.png", "data:image/png;base64,iVBORw0KGgo..."]
}
```

返回：

```json
{"asset": {"name": "cover_bg.png", "relPath": "assets/cover_bg.png", ...}}
```

### 5. 插入页面

#### 作为 image 元素

```python
api.insert(path, {
    "type": "image",
    "name": "封面-主视觉",
    "x": 0, "y": 0, "w": 1280, "h": 720,
    "props": {"src": "assets/cover_bg.png", "fit": "cover"}
})
```

`fit` 取值：`cover`（裁剪铺满，封面/背景常用） / `contain`（完整显示，产品图常用） / `fill`（拉伸）。

#### 作为页面背景

```python
api.update_page(path, {
    "background": {
        "type": "image",
        "image": "assets/cover_bg.png",
        "fit": "cover"
    }
})
```

**不要**用满幅 `image` 元素当背景——会盖住内容、每页各存一份。

### 6. 失败 fallback

如果 `image_search` / `image_generation` 返回失败、结果不可用、或工具不存在，**立刻退回图槽位**：

```python
api.insert(path, {
    "type": "shape",
    "name": "图槽-01",
    "x": 80, "y": 180, "w": 560, "h": 360,
    "props": {"shape": "rect"},
    "style": {"background": "#E8EEF6", "borderWidth": 1, "borderColor": "#C2CDDC"}
})
api.insert(path, {
    "type": "text",
    "name": "图槽-01-注",
    "x": 80, "y": 548, "w": 560, "h": 40,
    "props": {"text": "图槽-01：此处需补充产品实景图"},
    "style": {"fontSize": 13, "color": "#5A6A7D"}
})
```

将来替换时，只改 `props.src` 与 `fit`。

## 常见反面模式

- ❌ 拿 `image_generation` 画流程图、架构图、数据图；
- ❌ 让生图写中文 / 数字 / 字母；
- ❌ `props.src` 写成 `https://...` 外链；
- ❌ 拿到搜图/生图结果不检查水印、截图边框、乱码文字；
- ❌ 一页塞多张照片，导致版面散掉；
- ❌ 搜图/生图失败后硬等或空着，不留图槽位。

## 与本工程其他机制的关系

- **矢量优先**：照片只解决「真实场景 / 氛围」问题，结构 / 流程 / 数据仍用 `shape` / `path` / `connector` / `chart` / 图标库。
- **微场景**：照片是静态的；需要「动」的部分用 `scene` 元素。
- **页面背景**：整页底板 / 全篇背景用 `update_page(..., all_pages=True)`，不要用满幅 `image`。
