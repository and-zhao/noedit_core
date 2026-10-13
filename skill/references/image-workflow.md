# 图片插入工作流（搜图 / 生图 → 落入工程 → 插入页面）

本文件给**有出图能力的 Agent** 用：明确什么时候该配图、怎么调用工具、怎么把结果安全地落进 NoEdit Core 工程。
出图工具在不同环境里名字不同（`image_search` / `image_generation` / `ImageGen` / 文生图 / 画图插件 / 只有联网搜索），
**有哪个用哪个**；只有搜索没有专用搜图工具时，用搜索拿到图片直链后走 `api.import_asset_url`。

## 核心约束

1. **`props.src` 只能写工程内 `assets/` 的相对路径**（如 `assets/xxx.jpg`）。**不许写 http(s) 外链**——导出件必须离线自包含。
2. **照片感配图才能用搜图/生图**；结构图 / 原理图 / 流程图 / 装置图 / 数据图**必须用矢量**（`shape` / `path` / `connector` / `chart` / 图标库）。
3. **生图/搜图出来的图不得带文字/数字/水印/截图边框**——有文字就用 `text` 元素叠上去。
4. 图片风格必须贴全篇 **6 色 token**，不要出现体系外颜色。

## 什么时候必须主动用搜图 / 生图

在阶段 0（侦察 + 材料就绪）列出每页配图需求，只要满足以下任一条件，**且环境有任何出图手段（生图工具、搜图工具、或能联网搜到图片直链），就必须主动去拿图**：

- 封面需要主视觉 / 氛围图；
- 内容页需要真实场景、产品外观、人物、材质、风景等「照片感」内容；
- 用户明确说「配张图」但还没给图；
- 当前工程 `assets/` 为空，而设计需要非矢量视觉元素。

不要等用户催。没有工具或工具失败时，**立即退回图槽位**。

## 标准动作（七步）

### 1. 判断配图位置与数量

| 页面类型 | 建议 | 说明 |
| --- | --- | --- |
| 封面 | **1 张主视觉** | 可满幅，常作页面背景 |
| 章节过渡页 | 0–1 张氛围图 | 可有可无，优先用矢量装饰 |
| 数据 / 流程 / 原理页 | **不配照片** | 用矢量图讲清楚 |
| 产品介绍 / 团队 / 案例页 | 1 张产品 / 团队照片 | 搜图或用户供图 |
| 结尾致谢页 | 0–1 张氛围图 | 小尺寸装饰即可 |

**一页最多 1 张主图**，避免照片喧宾夺主。

### 2. 搜图（要真实场景 / 产品 / 人物时优先）

有专用搜图工具就用；没有就用联网搜索找到**图片直链**，然后：

```python
rec = api.import_asset_url(path, "https://.../robot-arm.jpg", "机械臂实景")
```

`import_asset_url` 会做四件事，别自己手写下载：带浏览器 UA（图床对裸 UA 常回 403）、
超时 20s + 退避重试 3 次、按文件头复核确实是图片（跳转页 / 防盗链 HTML 会当场报错，
不会留下一张打不开的假素材）、单个文件上限 25 MB。失败抛 `CoreError` 并写明原因。

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
- **短边 ≥ 版面显示尺寸**（`check_media` 会把缩略图尺寸的图点出来）；
- 商用 / 对外交付时注意版权——拿不准就改用生图。

### 3. 生图（搜不到、需特定氛围、或要避版权时用）

调用环境的生图能力（工具名各环境不同：`image_generation` / `ImageGen` / 文生图……）。

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

**尺寸按版面选**：主视觉 / 满幅背景取横图（16:9 或 3:2），窄栏配图取竖图，
别拿 1:1 去铺横条（`fit:cover` 会裁掉大半画面）。

**生完必须回读再导入**：用环境的读图能力看一眼这个文件，确认主体正确、没糊、没夹带文字 / 水印。
工具返回的路径**立刻** `import_asset` 导入，不要假设它下一轮还在原地、或文件名还是那个。

### 4. 落入工程

#### 拿到文件路径

```python
rec = api.import_asset(path, [r"D:\pics\cover_bg.png"])["imported"][0]
print(rec)
# {"name":"cover_bg.png","relPath":"assets/cover_bg.png","kind":"image","width":1024,"height":683,...}
# 同批还有 "problems": [{"source": "...", "reason": "文件不存在或不是文件", "imported": false}, ...]
```

**`problems` 不是可选阅读项**：`imported: false` 表示这张图根本没进工程——页面照做的话，成品里就是
一块空白。看到就当场处理：改对路径重导 / 换一张 / 实在没有就退回图槽位。**同一张图最多重试 2 次**，
别把整份稿子卡在一张图上。

#### 拿到 dataURL / URL / 字节

- 拿到的是**网络图片直链** → `api.import_asset_url(path, url, filename)`（自带重试与图片头复核，别手写下载）；
- 拿到 **dataURL / 字节** → 走 UI 通道上传（POST `/api/call`）：

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

如果搜图 / 生图返回失败、结果不可用、或环境根本没有这类工具，**立刻退回图槽位**：

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

### 7. 导出前体检

```python
c = api.check_media(path)
# {"ok": false, "refs": 12, "problems": [{"page":0,"element":"封面-主视觉","prop":"src",
#   "value":"assets/cover_bg.png","problem":"素材文件不存在（assets/cover_bg.png）"}, ...]}
```

`problems` 会把这几类问题按页 / 元素 / 属性点名：文件不在盘上、`props.src` 写了 http(s) 外链或工程外
绝对路径、没落在 `assets/` 下、图片解不开、尺寸像是缩略图、数字人 / 视频的 `poster` 指向 mp4。
**`ok=False` 就别导出**：补图、`attach_dh_posters` 补封面帧，或换成图槽位。漏网的断图在这一步会被抓住，
不用靠肉眼翻页面。

## 常见反面模式

- ❌ 拿生图画流程图、架构图、数据图；
- ❌ 让生图写中文 / 数字 / 字母；
- ❌ `props.src` 写成 `https://...` 外链；
- ❌ 拿到搜图/生图结果不检查水印、截图边框、乱码文字；
- ❌ **生完图不回读、导入后不看 `problems` 就继续排版**（成品少图多半就是这么来的）；
- ❌ 手写 `requests` / `curl` 下载搜来的图还不校验内容，把 403 页面当成图存进 `assets/`（用 `import_asset_url`）；
- ❌ 同一张图反复重试、或整页配图全靠一张图，卡死在一处（重试上限 2 次，然后走图槽位）；
- ❌ 一页塞多张照片，导致版面散掉；
- ❌ 搜图/生图失败后硬等或空着，不留图槽位。

## 与本工程其他机制的关系

- **矢量优先**：照片只解决「真实场景 / 氛围」问题，结构 / 流程 / 数据仍用 `shape` / `path` / `connector` / `chart` / 图标库。
- **微场景**：照片是静态的；需要「动」的部分用 `scene` 元素。
- **页面背景**：整页底板 / 全篇背景用 `update_page(..., all_pages=True)`，不要用满幅 `image`。
