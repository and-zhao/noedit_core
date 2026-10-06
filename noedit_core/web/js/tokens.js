/* ============================================================================
 * tokens.js —— 样式 token 表「唯一事实来源」
 *
 * HTML 渲染（render-kit.js）、PPTX / SVG 写入（app/export.py）两端都读这一份，
 * 颜色、投影、圆角这类「效果类属性」只在这里写一次，避免各端各写一份而漂移。
 *
 * 约束（重要）：window.AC_TOKENS 后面必须是**严格 JSON** 字面量 ——
 *   app/export.py 用同一个正则把这段字面量抠出来 json.loads，
 *   所以这里不能有注释、尾逗号、单引号、undefined、表达式。
 *
 * 与 render-kit.js 的关系：本文件必须先于 render-kit.js 加载。
 *   - 编辑器：web/index.html 里的 <script src="js/tokens.js">
 *   - 导出页：app/projects.py 的 _render_kit_script() 内联
 *   render-kit.js 里留了一份等值的兜底表，仅供本文件缺失时页面不崩，改色请改这里。
 * ==========================================================================*/
window.AC_TOKENS = {
  "version": 1,
  "shadow": {
    "code": { "dx": 0, "dy": 8, "blur": 22, "spread": 0, "color": "#101828", "alpha": 0.16 },
    "table": { "dx": 0, "dy": 6, "blur": 18, "spread": 0, "color": "#101828", "alpha": 0.12 }
  },
  "code": {
    "dark": {
      "bg": "#1e2430", "bar": "#181d27", "fg": "#e6edf3", "dim": "#7d8799",
      "line": "#2b3242", "accent": "#4aa8ff", "hl": "rgba(74,168,255,.12)", "dot": "#39404f",
      "tk": {
        "com": "#6b7a8f", "str": "#9ad48a", "num": "#f0a45d", "kw": "#c678dd",
        "type": "#e5c07b", "fn": "#61afef", "op": "#56b6c2", "punc": "#a6b0bf",
        "var": "#e6edf3", "key": "#7ec8e3", "tag": "#e06c75", "attr": "#d19a66",
        "anno": "#d19a66"
      }
    },
    "light": {
      "bg": "#f7f8fa", "bar": "#eceff3", "fg": "#24292f", "dim": "#8b939e",
      "line": "#dde2e8", "accent": "#1a73e8", "hl": "rgba(26,115,232,.10)", "dot": "#c4cbd4",
      "tk": {
        "com": "#8a9199", "str": "#0a7b34", "num": "#b76b01", "kw": "#a626a4",
        "type": "#986801", "fn": "#1a5fd0", "op": "#0184bc", "punc": "#5c6370",
        "var": "#24292f", "key": "#005cc5", "tag": "#d73a49", "attr": "#e36209",
        "anno": "#e36209"
      }
    }
  },
  "table": {
    "rowBg": "#ffffff",
    "altBg": "#f7f9fc",
    "borderColor": "#d0d5dd",
    "headerBg": "#f2f4f7",
    "headerColor": "#1f2328"
  },
  "geometry": {
    "table": {
      "lineHeight": 1.35,
      "minColEm": 4,
      "cjkEm": 1,
      "latinEm": 0.55
    }
  },
  "chart": {
    "axis": "#98a2b3",
    "grid": "#e4e7ec",
    "label": "#475467",
    "defaultPalette": ["#2f6fed", "#f2a33c", "#34b98a", "#e46a76", "#8a7cf0",
                       "#3fb6d3", "#b57ce0", "#f0755f", "#5aa469", "#d9a441"]
  }
};
