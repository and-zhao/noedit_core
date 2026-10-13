# NoEdit Core · 数字人播报模块（Digital Human，可选拆出）

本模块给 PPT 增加**数字人播报**能力：输入一张真人照片 + 一段讲稿音频，生成一段口型同步的说话人视频，作为页面元素插入（导出 HTML / PPTX 都能播放）。

> **设计原则：完全可选、可拆。** 不需要数字人的用户可以不安装本模块；核心 `noedit_core` 在不安装 `dh` 依赖时仍能正常运行（`digital_human` 元素类型会防御性降级）。

## 目录

- [什么时候需要数字人](#什么时候需要数字人)
- [方案对比与许可](#方案对比与许可)
- [模块拆分 / 卸载步骤](#模块拆分--卸载步骤)
- [安装](#安装)
- [引擎说明](#引擎说明)
- [Python API](#python-api)
- [与 NoEdit Core 集成](#与-noedit-core-集成)
- [AI Agent 用法](#ai-agent-用法)
- [已知限制](#已知限制)

---

## 什么时候需要数字人

| 场景 | 建议 |
| --- | --- |
| 无人讲解的线上路演 / 产品介绍 | 用数字人代替真人出镜，降低制作成本 |
| 多语言版本批量生成 | 同一讲稿换不同音色/口型，快速出多语言视频 |
| 教学课件 / 慕课 | 虚拟讲师反复讲解同一页内容 |
| 现场有人演讲的场合 | **不建议**——真人与数字人声音互相干扰 |
| 版权 / 隐私敏感场景 | 优先用用户自己授权的人像照片或合成形象 |

## 方案对比与许可

> **"可商用"是就代码许可证与官方公开声明的通常理解，不构成法律意见；部署前请自行核对目标方案当时的官方 LICENSE 与模型权重声明。**

### 开源/本地方案

| 方案 | 类型 | 运行位置 | 效果 | License / 商用限制 | 推荐用途 |
| --- | --- | --- | --- | --- | --- |
| **LivePortrait**（快手 KlingAI） | 单图驱动表情/头部动画 | 本地 GPU | 头部自然、速度快 | 代码 **MIT**（宽松可商用）；预训练权重属快手发布物，商用请核对官方权重声明 | **默认推荐**：照片 + 音频生成播报视频 |
| **SadTalker**（CVPR 2023） | 单图 + 音频生成说话人脸 | 本地 GPU | 口型同步较好、成熟 | 代码 **MIT**（宽松可商用）；预训练模型按官方发布声明 | **备选**：照片 + 音频对口型 |
| **MuseTalk**（腾讯音乐） | 实时口型同步（视频换嘴） | 本地 GPU | 实时、适合已有视频 | Apache-2.0（以官方仓库当时的 LICENSE 为准） | 给已有真人视频换口型 |
| **Wav2Lip** | 视频 + 音频口型同步 | 本地 GPU | 经典基线、分辨率低 | **严禁商用**：官方 README 明确 "research / academic / personal purposes only"，模型在 LRS2 数据集上训练 | **不推荐**，仅个人研究 |
| **GeneFace++** | NeRF Talking Head | 本地 GPU | 高真实感、需逐人训练 | 研究代码，未给出宽松商用许可 | 非商用实验 |
| **ER-NeRF** | NeRF Talking Head | 本地 GPU | 高真实感、需逐人训练 | 研究代码，未给出宽松商用许可 | 非商用实验 |

### 云端 API 方案（按量付费）

| 方案 | 运行位置 | 效果 | 商用限制 | 推荐用途 |
| --- | --- | --- | --- | --- |
| **Azure Speech Avatar** | 微软云 | 效果最好、带动作与 TTS | 付费云服务，需遵守微软服务条款 | 企业级商用首选 |
| **腾讯云智能数智人** | 腾讯云 | 效果好、中文优化 | 付费云服务 | 国内商用首选 |
| **阿里云通义数字人** | 阿里云 | 效果好 | 付费云服务 | 国内商用备选 |

**选型建议**：

- **个人 / 小团队 / 不想花钱**：先用 `lightweight` 引擎（无 GPU、无模型下载）跑通全链路；有能力再切 `liveportrait` 或 `sadtalker`。
- **要效果且接受付费**：`cloud` 引擎目前只有**桥接骨架**（配置读取 + provider 分发已就位，
  submit/poll/download 三步还没接各家 SDK）。填了 key 后 `dh_status()` 会直说「桥接未接入」，
  要商用云效果需自行在 `engines/cloud_engine.py` 补三家分支。
- **避免 Wav2Lip 做任何商用产品**——License 风险大。

## 模块拆分 / 卸载步骤

本模块所有代码都在 `noedit_core/dh/` 一个目录内；核心代码没有硬依赖它。

### 拆分出去（单独成一个包）

```
1. 把 noedit_core/dh/ 目录整体复制到新仓库根目录
2. dh/README.md 改作新包 README（内容已自包含）
3. 新包新增 pyproject.toml，包名建议 noedit-dh
4. 保留 dh/engines/ 与 generator.py、validator.py
5. （可选）把 api.py 中带 dh_ 前缀的函数一并复制作为独立入口
```

### 从 NoEdit Core 卸载（不想用数字人）

```bash
# 1. 删除模块目录
cd noedit_core/noedit_core
rm -rf dh/          # Windows: rmdir /s /q dh

# 2. （可选）卸载不再需要的依赖
pip uninstall torch torchvision torchaudio -y   # 仅当没别的用途

# 3. 核心照常运行：digital_human 元素类型自动降级不识别，UI 不显示数字人入口
```

### 最小安装（只想用轻量引擎）

```bash
pip install -r noedit_core/noedit_core/dh/requirements-lightweight.txt
```

### 完整安装（本地 GPU 引擎）

```bash
pip install -r noedit_core/noedit_core/dh/requirements.txt
```

## 安装

```bash
cd noedit_core/noedit_core/dh

# 按引擎选择依赖
pip install -r requirements-lightweight.txt   # lightweight（先跑通）
pip install -r requirements.txt              # liveportrait / sadtalker（GPU）
pip install -r requirements-cloud.txt        # cloud（仅需 requests）

# 下载模型权重（仅本地 GPU 引擎）
python -m noedit_core.dh.validator --download liveportrait
python -m noedit_core.dh.validator --download sadtalker

# 验证环境
python -m noedit_core.dh.validator
```

验证输出示例：

```
lightweight : OK
liveportrait: missing torch
sadtalker   : missing checkpoints
cloud       : no config set
```

## 引擎说明

### lightweight（轻量占位引擎）

- **无深度学习依赖**，只需 `ffmpeg` + `Pillow`
- 给静态照片做**缓慢呼吸缩放 + 轻微亮度脉动**，叠加音频轨合成 MP4
- 效果不逼真，但**能立即验证「照片 → 视频 → 页面元素 → 导出」整条链路**
- 适合没 GPU、没模型、只想跑通流程的场景

### liveportrait（默认推荐）

- 输入：1 张正脸照片 + 1 段音频
- 输出：带口型/头部动作的 MP4
- 需要：PyTorch（CUDA 或 CPU）、模型权重（`validator --download`）

### sadtalker（备选）

- 输入：1 张正脸照片 + 1 段音频
- 输出：说话人脸 MP4
- 需要：PyTorch、官方 checkpoint

### cloud（商用效果首选，**桥接待接入**）

- 输入：1 张照片（或形象 ID）+ 1 段文本（云端 TTS + 数字人合成一体）
- 输出：云端生成的 MP4 URL → 下载落 `assets/`
- 需要：`dh/cloud_config.json`（复制 `cloud_config.example.json` 填入自己的 key），
  并在 `_azure` / `_tencent` / `_aliyun` 三个方法里按各家 SDK 补 submit → poll → download（约 30 行/家）
- 现状：三家分支都会抛「未接入」的 `EngineError`，`check()` 也不会回报 `ok`——**不会假装能跑**

## Python API

```python
import sys
sys.path.insert(0, r"path\to\noedit_core")

# 1. 生成数字人视频（返回生成文件路径）
from noedit_core.dh import generator
out = generator.generate(
    image=r"D:\pics\host.png",          # 真人照片
    audio=r"D:\tts\p1.wav",             # 讲稿音频
    engine="auto",                      # auto: 依序探测 liveportrait → sadtalker → lightweight，
                                        #       某档运行期崩了会自动降级到下一档（见返回的 tried / note）
    out_dir=r"D:\out",                  # 输出目录
    poster=True,                        # 顺带从成片抽一张封面帧 JPG（PPTX / PDF 就靠它）
)
print(out["video"], out["poster"], out["engine"])   # -> D:\out\host_p1.mp4  D:\out\host_p1_poster.jpg  lightweight

# 2. 落进工程并插入页面
from noedit_core import api
P = api.create_project("带数字人的PPT", r"D:\work")["path"]
rec = api.import_asset(P, [out["video"]] + ([out["poster"]] if out["poster"] else []))
vid = rec["imported"][0]["relPath"]
poster = next((a["relPath"] for a in rec["imported"] if a["relPath"] != vid), "")
api.insert(P, {
    "type": "digital_human",
    "name": "页1-数字人",
    "x": 880, "y": 400, "w": 360, "h": 300,   # 右下角，不压正文
    "props": {
        "src": vid,                           # assets/host_p1.mp4
        "poster": poster,                     # 封面帧图片；忘了就留空，再用 attach_dh_posters 补
        "autoplay": True, "loop": False,
        "controls": False, "muted": False,
        "volume": 1.0,
        "startAt": 0,                          # 进入页面第几秒开始
    },
}, page_index=0)
```

**环境探测**（不装重依赖也能先跑轻量档）：

```python
from noedit_core.dh import validator
print(validator.check_all())   # {'lightweight': 'ok', 'liveportrait': 'missing torch', ...}
```

**封面帧补救 + 导出前体检**（已经建好的工程忘了 poster、或 poster 误写成 mp4 时用）：

```python
from noedit_core import api
print(api.attach_dh_posters(P))   # 从每个 digital_human / video 自己的 mp4 抽一帧，落 assets/ 并回写 props.poster
print(api.check_media(P))         # 断图 / 外链 / poster 指向 mp4 都会点名到页 + 元素 + 属性
```

## 与 NoEdit Core 集成

| 层 | 行为 |
| --- | --- |
| **schema** | `web/element-schema.json` 新增 `digital_human` 类型（字段与 video 同构 + `startAt`） |
| **渲染** | `core/projects.py` 把 `digital_human` 渲染为带 `data-ac-video` 的 `<video>`（含音频），进入视口按 `startAt` 自动播（复用视频运行时） |
| **导出 PPTX** | `core/export.py` 复用视频链路：`add_movie` 真嵌 MP4，放映可播可听 |
| **导出 PDF / PNG / SVG** | 渲染静态封面帧（人像 + 名字条），不破坏版面 |
| **UI** | 导出面板弹窗提供三种演示模式：**纯 PPT / 音频模式 / 数字人模式**；属性面板支持上传照片生成 |
| **Agent Skill** | `skill/SKILL.md`「数字人策略」+ `references/digital-human-workflow.md` |

## AI Agent 用法

Agent 有本地引擎或云端 key 时**主动询问用户**要不要数字人模式；确认后按五步走：

1. **要照片**：请用户提供一张正脸照，或用生图工具合成一个虚拟形象（提示词：professional portrait, front-facing, plain background, neutral lighting）；
2. **要讲稿音频**：按该页内容写口语化讲稿 → TTS 合成（或走 `audio` 模块的合成流程）；
3. **生成视频**：`dh.generator.generate(image, audio, engine="auto")`；
4. **落入工程**：`import_asset` → `assets/`；
5. **插入元素**：`insert(type="digital_human", props={"src": rec["relPath"], ...})`，右下角摆放不压正文。

**没有引擎也没有 key** → 老实回退到「音频模式」或纯 PPT，不要硬塞一个不会说话的假人。

## 已知限制

- `lightweight` 引擎**不做真口型同步**——只是呼吸缩放 + 音画合并，用于跑通流程；
- `liveportrait` / `sadtalker` 需要 GPU（CPU 可跑但极慢）；模型权重需单独下载；
- `digital_human` 元素本质是一段带声视频：**页内多条时会互相抢声音**，一页最多 1 个数字人；
- 云引擎的输出 URL 必须下载落 `assets/` 再引用，**不许直接把外链写进 `props.src`**；
- 使用真人照片必须**获得当事人授权**；合成形象也请注意肖像权 / 平台条款。
