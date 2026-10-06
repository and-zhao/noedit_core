# 第三方组件声明 · Third-Party Notices

NoEdit Core 本身以 **PolyForm Noncommercial License 1.0.0** 授权，全文见 [LICENSE](LICENSE)。

本文件列出随仓库分发、或运行时会用到的第三方组件及其许可。这些组件的版权归各自作者所有，
其许可条款适用于对应部分，并优先于本项目许可。

---

## 一、随仓库分发的第三方组件

### 1. KaTeX — MIT License

- 上游：https://github.com/KaTeX/KaTeX
- 位置：`noedit_core/web/vendor/katex/`（`katex.min.js`、`katex.min.css`、`fonts/`）
- 用途：公式（LaTeX）排版
- 许可全文：随包附带，见 `noedit_core/web/vendor/katex/LICENSE`

### 2. draw.io stencil libraries — Apache License 2.0

- 上游：https://github.com/jgraph/drawio
- 路径 / ref：`src/main/webapp/stencils` @ `dev`
- 位置：`noedit_core/web/icon-catalog.json`（1800+ 矢量图标，由上游 SVG 几何誊写为可编辑的 path 数据）
- 商标与图标条款：上游声明**不得用于 Atlassian 产品**；终端用户用本工具产出的内容不受此限
- 许可全文：https://github.com/jgraph/drawio/blob/dev/LICENSE
- 合规提示：Apache-2.0 要求分发时附带许可副本。本仓库暂未内置上游 LICENSE 文件，
  若你要做严格的合规分发，请从上述地址取一份随包附带。

### 3. Apollon — MIT License

- 上游：https://github.com/ls1intum/Apollon
- 路径 / ref：`library/lib/components/svgs/nodes` @ `bdb9dcd`
- 位置：`noedit_core/web/icon-catalog-uml.json`（UML 与流程图形状，几何誊自上游各节点 React 组件的 SVG 原语）
- 许可全文：https://github.com/ls1intum/Apollon/blob/main/LICENSE

### 4. Bioicons — CC0 / MIT / BSD

- 上游：https://github.com/duerrsimon/bioicons
- 路径 / ref：`static/icons`（仅取宽松许可目录）@ `main`
- 位置：`noedit_core/web/icon-catalog-bio.json`（分子、基因、细胞等科研图标）
- 逐图标署名：见 `icon-catalog-bio.json` 中各分组与图标携带的 `license` / `author` 字段
- 许可说明：https://github.com/duerrsimon/bioicons

---

## 二、运行时不随仓库分发、按需从 CDN 下载

微场景（`scene`）用到的 JS 库**不随本仓库分发**，由 `install_scene_lib` 在用户本机按需下载到本地缓存
（清单见 `noedit_core/core/scene_libs.py`）。各库版权归其作者，条款以其上游为准：

| 库 | 版本 | 上游 | 许可 |
| --- | --- | --- | --- |
| p5.js | 1.9.4 | https://github.com/processing/p5.js | LGPL-2.1 |
| anime.js | 3.2.2 | https://github.com/juliangarnier/anime | MIT |
| GSAP | 3.12.5 | https://github.com/greensock/GSAP | GreenSock 标准许可（多数场景免费，部分插件与用途另有条款） |
| Three.js | 0.147.0 | https://github.com/mrdoob/three.js | MIT |
| Chart.js | 4.4.1 | https://github.com/chartjs/Chart.js | MIT |
| D3.js | 7.8.5 | https://github.com/d3/d3 | ISC |
| Matter.js | 0.19.0 | https://github.com/liabru/matter-js | MIT |
| canvas-confetti | 1.9.2 | https://github.com/catdad/canvas-confetti | ISC |

---

## 三、Python 依赖（不随仓库分发，由用户自行安装）

| 依赖 | 许可 | 用途 |
| --- | --- | --- |
| python-pptx | MIT | 导出 pptx |
| Pillow | MIT-CMU（Pillow License） | 图片格式转换、微场景抓帧合成 GIF |
| playwright（可选） | Apache-2.0 | 微场景抓帧；未安装时回退本机 Edge / Chrome |

pdf / png / svg 导出依赖本机 **Edge 或 Chrome**，浏览器本身不随本仓库分发。
