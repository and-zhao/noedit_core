/* ============================================================================
 * render-kit.js —— 元素内容的「单份实现」
 *
 * 为什么是一个「经典脚本」而不是 ES 模块：
 *   同一份渲染逻辑要同时跑在四个地方 ——
 *     1. 编辑器画布（web/js/canvas.js 的 RENDERERS）
 *     2. 静态 HTML 导出（app/projects.py 的 render_static_html）
 *     3. PDF / 打印
 *     4. PPTX 栅格截图（app/projects.py 的 render_raster_sheet_html）
 *   后三处由 Python 生成 HTML，直接把这个文件的源码内联进 <script> 里即可，
 *   不需要知道模块系统。所以这里不写 import / export，只挂 window.ACRender。
 *
 * 约束：本文件源码会被塞进 <script> 标签内联，因此文中
 *   绝不能出现字面量「<」+「/script」这七个字符，否则会提前闭合标签。
 *
 * 约定：所有对外函数都返回「HTML 字符串」，不接受 DOM、不查询 DOM（mountAll 除外）。
 * ==========================================================================*/
(function (global) {
  'use strict';

  var ACRender = {};

  // ---------------------------------------------------------------- 基础工具
  function esc(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  /** 属性值转义（进 HTML 属性的字符串）。 */
  function escAttr(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function num(value, fallback) {
    var n = Number(value);
    return isFinite(n) ? n : fallback;
  }

  function clamp(v, lo, hi) {
    return v < lo ? lo : (v > hi ? hi : v);
  }

  /** 只保留看上去像颜色的字符串，避免把任意用户输入直接写进 style。 */
  function safeColor(value, fallback) {
    var s = String(value === null || value === undefined ? '' : value).trim();
    if (!s) return fallback || '';
    if (/^#[0-9a-fA-F]{3,8}$/.test(s)) return s;
    if (/^rgba?\([0-9.,%\s]+\)$/.test(s)) return s;
    if (/^hsla?\([0-9.,%\s]+\)$/.test(s)) return s;
    if (/^[a-zA-Z]{3,20}$/.test(s)) return s;
    return fallback || '';
  }

  function compactNum(n) {
    var a = Math.abs(n);
    if (a >= 1e8) return trimZero(n / 1e8) + '亿';
    if (a >= 1e4) return trimZero(n / 1e4) + '万';
    return trimZero(n);
  }

  function trimZero(n) {
    var r = Math.round(n * 100) / 100;
    return String(r);
  }

  /** 数值文本：统一走这里，保证编辑器 / 导出 / 截图三处完全一致。 */
  function fmtValue(v, fmt) {
    var n = num(v, 0);
    switch (fmt) {
      case 'percent': return trimZero(n) + '%';
      case 'compact': return compactNum(n);
      case 'fixed1': return n.toFixed(1);
      case 'fixed2': return n.toFixed(2);
      case 'none': return '';
      case 'thousand': return n.toLocaleString('en-US');
      default: return trimZero(n);
    }
  }

  ACRender.esc = esc;
  ACRender.fmtValue = fmtValue;
  ACRender.compactNum = compactNum;

  // ---------------------------------------------------------------- 样式 token
  /* web/js/tokens.js 是唯一样式来源（编辑器、静态导出、探针页都先加载它）。
   * 下面这份兜底表只在 tokens.js 没加载时顶上，值必须与 tokens.js 保持一致。 */
  var FALLBACK_TOKENS = {
    shadow: {
      code: { dx: 0, dy: 8, blur: 22, spread: 0, color: '#101828', alpha: 0.16 },
      table: { dx: 0, dy: 6, blur: 18, spread: 0, color: '#101828', alpha: 0.12 },
    },
  };

  var TOKENS = (global && typeof global.AC_TOKENS === 'object' && global.AC_TOKENS)
    ? global.AC_TOKENS : FALLBACK_TOKENS;

  /** 按路径取 token，逐级兜底（tokens.js 缺哪一级就用 FALLBACK 的哪一级）。 */
  function tok() {
    var node = TOKENS, fb = FALLBACK_TOKENS;
    for (var i = 0; i < arguments.length; i++) {
      var key = arguments[i];
      node = node ? node[key] : undefined;
      fb = fb ? fb[key] : undefined;
    }
    return node === undefined || node === null || node === '' ? fb : node;
  }

  ACRender.tok = tok;

  /** 颜色 + 透明度 → rgba()；认不出颜色时退回纯黑。 */
  function rgbaOf(color, alpha) {
    var s = String(color === null || color === undefined ? '' : color).trim();
    var m = /^#?([0-9a-fA-F]{6})$/.exec(s);
    if (!m) return s || 'rgba(0,0,0,' + num(alpha, 1) + ')';
    var n = parseInt(m[1], 16);
    return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255)
      + ',' + num(alpha, 1) + ')';
  }

  /** 结构化投影 {dx,dy,blur,spread,color,alpha} → CSS box-shadow 值。 */
  function shadowCss(s) {
    if (!s) return 'none';
    return num(s.dx, 0) + 'px ' + num(s.dy, 0) + 'px ' + num(s.blur, 0) + 'px '
      + num(s.spread, 0) + 'px ' + rgbaOf(s.color, num(s.alpha, 1));
  }

  ACRender.rgbaOf = rgbaOf;
  ACRender.shadowCss = shadowCss;

  // ---------------------------------------------------------------- 样式自注入
  /* 样式跟着脚本走：编辑器在 index.html 里引入本文件、导出 HTML 由 Python 内联本文件，
   * 两条路径都只需注入一次，不需要再维护一份 CSS。 */

  /* 代码块两套主题的变量表：颜色只写在 tokens.js，这里生成 CSS 规则，
   * 让「浏览器渲染」与「导出端读同一份 token」天然一致。 */
  var CODE_VARS = ['bg', 'bar', 'fg', 'dim', 'line', 'accent', 'hl', 'dot'];
  var CODE_TKS = ['com', 'str', 'num', 'kw', 'type', 'fn', 'op', 'punc', 'var', 'key',
                  'tag', 'attr', 'anno'];

  function codeThemeCss() {
    return ['dark', 'light'].map(function (theme) {
      var decls = [];
      CODE_VARS.forEach(function (k) {
        var v = tok('code', theme, k);
        if (v) decls.push('--ac-' + k + ':' + v);
      });
      CODE_TKS.forEach(function (k) {
        var v = tok('code', theme, 'tk', k);
        if (v) decls.push('--tk-' + k + ':' + v);
      });
      return '.ac-code[data-theme="' + theme + '"]{' + decls.join(';') + ';}';
    });
  }

  var CSS_TEXT = [
    /* ---- 代码块（CSDN 风格：外框 + 标题栏 + 行号 + 高亮行） ---- */
    '.ac-code{position:relative;display:flex;flex-direction:column;width:100%;height:100%;',
    'border-radius:var(--ac-radius,8px);overflow:hidden;background:var(--ac-bg);color:var(--ac-fg);',
    'font-family:var(--ac-font);font-size:var(--ac-fs);line-height:var(--ac-lh);',
    'box-shadow:var(--ac-shadow);border:1px solid var(--ac-line);}',
    '.ac-code[data-shadow="0"]{box-shadow:none;}',
    '.ac-code-bar{flex:none;display:flex;align-items:center;gap:8px;padding:0 12px;height:34px;',
    'background:var(--ac-bar);border-bottom:1px solid var(--ac-line);user-select:none;}',
    '.ac-code-bar.is-mac{padding-left:10px;}',
    '.ac-dots{display:inline-flex;gap:6px;flex:none;}',
    '.ac-dots i{width:10px;height:10px;border-radius:50%;background:var(--ac-dot);display:block;}',
    '.ac-dots i:nth-child(1){background:#ff5f57;}',
    '.ac-dots i:nth-child(2){background:#febc2e;}',
    '.ac-dots i:nth-child(3){background:#28c840;}',
    '.ac-dots.is-plain i{background:var(--ac-dot);}',
    '.ac-code-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;',
    'font-size:calc(var(--ac-fs) * .92);color:var(--ac-dim);text-align:center;}',
    '.ac-code-lang{flex:none;font-size:calc(var(--ac-fs) * .82);letter-spacing:.08em;text-transform:uppercase;',
    'color:var(--ac-accent);border:1px solid var(--ac-accent);border-radius:10px;padding:1px 8px;opacity:.9;}',
    '.ac-code-body{flex:1;min-height:0;display:flex;overflow:hidden;}',
    '.ac-code-gutter{flex:none;text-align:right;padding:var(--ac-pad) 10px var(--ac-pad) 14px;',
    'color:var(--ac-dim);background:var(--ac-bar);user-select:none;overflow:hidden;border-right:1px solid var(--ac-line);}',
    '.ac-code-gutter span{display:block;}',
    '.ac-code-scroll{flex:1;min-width:0;overflow:auto;}',
    '.ac-code-pre{margin:0;padding:var(--ac-pad) 14px;font:inherit;',
    'white-space:var(--ac-wrap,pre);tab-size:var(--ac-tab,4);}',
    '.ac-code-pre code{font:inherit;color:inherit;background:none;}',
    '.ac-code-row{display:block;min-height:var(--ac-lh-em);border-radius:3px;}',
    '.ac-code-row.is-hl{background:var(--ac-hl);box-shadow:inset 2px 0 0 var(--ac-accent);}',
    '.ac-code-empty{opacity:.45;font-style:italic;}',
    /* 深色 / 浅色主题：--ac-* 与 --tk-* 全部由 tokens.js 生成，见下方 codeThemeCss() */
    '.tk-com{color:var(--tk-com);font-style:italic;}',
    '.tk-str{color:var(--tk-str);}',
    '.tk-num{color:var(--tk-num);}',
    '.tk-kw{color:var(--tk-kw);}',
    '.tk-type{color:var(--tk-type);}',
    '.tk-fn{color:var(--tk-fn);}',
    '.tk-op{color:var(--tk-op);}',
    '.tk-punc{color:var(--tk-punc);}',
    '.tk-var{color:var(--tk-var);}',
    '.tk-key{color:var(--tk-key);}',
    '.tk-tag{color:var(--tk-tag);}',
    '.tk-attr{color:var(--tk-attr);}',
    '.tk-anno{color:var(--tk-anno);}',
    '.tk-ins{color:#34b98a;}',
    '.tk-del{color:#e46a76;}',
    '.tk-err{color:#e46a76;text-decoration:underline wavy;}',
    /* ---- 表格 ---- */
    '.ac-table-wrap{width:100%;height:100%;overflow:visible;}',
    '.ac-table{width:100%;border-collapse:var(--ac-tb-collapse,collapse);',
    'border-spacing:0;font-family:var(--ac-tb-font,inherit);}',
    '.ac-table th,.ac-table td{vertical-align:var(--ac-tb-valign,middle);word-break:break-word;}',
    '.ac-table-empty{width:100%;height:100%;display:flex;align-items:center;justify-content:center;',
    'color:#98a2b3;font-size:12px;}',
    /* ---- 公式 ---- */
    '.tx-block{display:block;text-align:center;margin:.25em 0;}',
    '.tx-inline{padding:0 1px;}',
    '.ac-tex{font-family:"Cambria Math","Latin Modern Math","Times New Roman",serif;}',
    '.tx-frac{display:inline-flex;flex-direction:column;vertical-align:middle;text-align:center;margin:0 .12em;}',
    '.tx-frac-n{padding:0 .28em .06em;border-bottom:1px solid currentColor;}',
    '.tx-frac-d{padding:.06em .28em 0;}',
    '.tx-scr{display:inline-flex;flex-direction:column;font-size:.72em;line-height:1.16;margin-left:.1em;}',
    '.tx-sup,.tx-sub{display:block;}',
    '.tx-scr-up{vertical-align:.62em;}',
    '.tx-scr-dn{vertical-align:-.24em;}',
    '.tx-scr-b{vertical-align:.625em;}',
    '.tx-scr-b .tx-sup{margin-bottom:-.3em;}',
    '.tx-big{display:inline-flex;flex-direction:column;align-items:center;vertical-align:middle;margin:0 .16em;line-height:1.06;}',
    '.tx-big .tx-big-op{font-size:1.45em;}',
    '.tx-big .tx-lim{font-size:.62em;font-style:normal;}',
    '.tx-big .tx-lim-up{margin-bottom:-.24em;}',
    '.tx-big .tx-lim-dn{margin-top:-.24em;}',
    /* 根号 = 左下固定小钩 + 竖直主杆（随被开方内容拉伸、粗细恒定）。
       关键：钩的右臂在顶部是一段竖直笔画，其中心线固定在 x=.25em；
       主杆（left:.225em、宽 .05em）的中心也是 .25em，两者严格同线、无横向台阶。
       主杆底端（bottom:.2em）落在钩的拐点上，任意高度都不会出现接缝。
       容器用 inline-block + padding-left 让「基线 = 被开方内容基线」，
       根号只是包在内容外向下伸展，不会把内容顶高（分式线才能与等号同高）。 */
    '.tx-sqrt{position:relative;display:inline-block;padding-left:.275em;margin:0 .16em 0 .08em;}',
    '.tx-sqrt-sym{position:absolute;left:0;top:0;bottom:0;width:.275em;}',
    '.tx-sqrt-bar{position:absolute;left:.225em;top:0;bottom:.2em;width:0;border-left:.05em solid currentColor;}',
    '.tx-sqrt-hook{position:absolute;left:0;bottom:0;width:.3em;height:.36em;}',
    '.tx-sqrt-hook svg{display:block;width:100%;height:100%;overflow:visible;}',
    '.tx-sqrt-hook path{fill:none;stroke:currentColor;stroke-width:5;stroke-linecap:round;stroke-linejoin:round;}',
    '.tx-sqrt-body{display:block;border-top:.05em solid currentColor;padding:.06em .22em 0;line-height:.9;}',
    '.tx-sqrt-idx{position:absolute;left:0;top:0;font-size:.6em;line-height:1;transform:translate(-.1em,-.9em);}',
    '.tx-mat{display:inline-table;vertical-align:middle;margin:0 .18em;border-collapse:separate;border-spacing:.18em .06em;}',
    '.tx-mat td{text-align:center;padding:0;}',
    '.tx-mat-delim{display:inline-block;vertical-align:middle;font-size:1.9em;line-height:1;transform:scaleY(1.05);}',
    '.tx-sys{display:inline-table;vertical-align:middle;margin:0 .18em;border-collapse:separate;border-spacing:.1em .1em;}',
    '.tx-sys td{padding:0;text-align:left;}',
    '.tx-sys td.tx-sys-l{text-align:right;padding-right:.3em;}',
    '.tx-sp{display:inline-block;}',
    '.tx-txt{font-family:inherit;font-style:normal;}',
    '.tx-bf{font-weight:700;}',
    '.tx-cal{font-family:"Segoe Script","Times New Roman",cursive;}',
    '.tx-ital{font-style:italic;padding-right:.045em;}',
    /* 关系符 / 二元运算符 / 标点：补回 TeX 的间隙，避免与相邻字母、根号接触重叠 */
    '.tx-rel{margin:0 .17em;}',
    '.tx-op{margin:0 .12em;}',
    '.tx-punc{margin-right:.12em;}',
    /* \\big \\Big \\bigg \\Bigg 放大的定界符：只放大自己、不把行高撑开 */
    '.tx-delim{display:inline-block;line-height:.9;vertical-align:-.14em;}',
    '.tx-acc{position:relative;display:inline-block;}',
    '.tx-acc .tx-acc-mk{position:absolute;left:0;right:0;text-align:center;line-height:1;}',
    '.tx-acc .tx-acc-mk.tx-acc-up{top:-.72em;}',
    '.tx-acc .tx-acc-mk.tx-acc-dn{bottom:-.62em;}',
    '.tx-acc .tx-acc-line{position:absolute;left:0;right:0;border-top:1px solid currentColor;}',
    /* \\underbrace \\overbrace：可伸缩花括号 + 居中标签 */
    '.tx-br{display:inline-flex;flex-direction:column;align-items:center;vertical-align:-.2em;margin:0 .12em;}',
    '.tx-br-body{display:block;}',
    '.tx-br-lab{display:block;font-size:.72em;line-height:1.15;white-space:nowrap;}',
    '.tx-br-hook{display:block;width:100%;height:.26em;box-sizing:border-box;'
      + 'border:1px solid currentColor;border-top:0;border-radius:0 0 .4em .4em;}',
    '.tx-br-hook.tx-br-up{border:1px solid currentColor;border-bottom:0;border-radius:.4em .4em 0 0;}',
    /* \\xrightarrow 等：箭头上下带标签 */
    '.tx-xa{display:inline-flex;flex-direction:column;align-items:center;vertical-align:-.3em;margin:0 .14em;}',
    '.tx-xa-lab{display:block;font-size:.72em;line-height:1.15;white-space:nowrap;}',
    '.tx-xa-ar{display:block;line-height:1;}',
    /* \\stackrel \\overset \\underset：上下堆叠 */
    '.tx-st{display:inline-flex;flex-direction:column;align-items:center;vertical-align:-.2em;line-height:1.06;}',
    '.tx-st-top{display:block;font-size:.72em;}',
    /* \\binom：无横线的分式 + 大括号 */
    '.tx-bin{display:inline-flex;align-items:center;}',
    '.tx-bin .tx-frac{vertical-align:0;margin:0;}',
    '.tx-bin .tx-frac-n{border-bottom:0;padding:0 .15em .04em;}',
    '.tx-bin .tx-frac-d{padding:.04em .15em 0;}',
    /* ---- 文本 ---- */
    '.ac-text{width:100%;word-break:break-word;}',
    '',
  ].concat(codeThemeCss()).join('\n');

  var CSS_INJECTED = false;
  /** 把渲染器样式挂到 <head>；重复调用无副作用。 */
  function injectCss() {
    if (CSS_INJECTED) return;
    if (typeof document === 'undefined' || !document.createElement) return;
    var head = document.head || document.documentElement;
    if (!head) return;
    if (document.getElementById('ac-render-css')) { CSS_INJECTED = true; return; }
    var style = document.createElement('style');
    style.id = 'ac-render-css';
    style.textContent = CSS_TEXT;
    head.appendChild(style);
    CSS_INJECTED = true;
  }

  ACRender.injectCss = injectCss;
  ACRender.CSS_TEXT = CSS_TEXT;

  // ---------------------------------------------------------------- 语法高亮
  /* 不引第三方库（宿主零依赖），自己写一个「粘性正则扫描器」：
   * 按规则数组的顺序在当前位置尝试匹配，命中就吃掉这段并标注 token 类。
   * 规则用 y（sticky）标志，从 lastIndex 处匹配，避免 slice 出 O(n^2)。 */

  function rx(source) { return new RegExp(source, 'y'); }

  var NUM_RE = /\b(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?[fFlLuUdDmM]*)\b/y;
  var CMT_SLASH = rx('\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/');
  var CMT_HASH = rx('#[^\\n]*');
  var CMT_DASH = rx('--[^\\n]*');
  var STR_DQ = rx('"(?:\\\\.|[^"\\\\\\n])*"');
  var STR_SQ = rx("'(?:\\\\.|[^'\\\\\\n])*'");
  var STR_BT = rx('`(?:\\\\[\\s\\S]|[^\\\\`])*`');
  var STR_TRIPLE = rx('"""[\\s\\S]*?"""|\'\'\'[\\s\\S]*?\'\'\'');

  function alt() {
    var parts = [];
    for (var i = 0; i < arguments.length; i++) if (arguments[i]) parts.push(arguments[i].source);
    return rx(parts.join('|'));
  }

  function wordRe(words) { return rx('\\b(?:' + words.replace(/\s+/g, '|') + ')\\b'); }

  function tokenize(src, rules) {
    var out = [];
    var i = 0;
    var n = src.length;
    while (i < n) {
      var hit = null;
      for (var k = 0; k < rules.length; k++) {
        var rule = rules[k];
        rule.r.lastIndex = i;
        var m = rule.r.exec(src);
        if (m && m[0] && m.index === i) { hit = { t: m[0], c: rule.c }; break; }
      }
      if (hit) { out.push(hit); i += hit.t.length; }
      else { out.push({ t: src.charAt(i), c: '' }); i += 1; }
    }
    return out;
  }

  function identRe() { return rx('[A-Za-z_$][\\w$]*'); }

  /** 按「词表式」配置拼装规则数组 —— 大多数语言只是词表不同。 */
  function buildRules(cfg) {
    var rules = [];
    if (cfg.comment) rules.push({ c: 'tk-com', r: cfg.comment });
    if (cfg.str) rules.push({ c: 'tk-str', r: cfg.str });
    if (cfg.anno) rules.push({ c: 'tk-anno', r: cfg.anno });
    if (cfg.pre) rules.push({ c: 'tk-anno', r: cfg.pre });
    rules.push({ c: 'tk-num', r: NUM_RE });
    if (cfg.kw) rules.push({ c: 'tk-kw', r: wordRe(cfg.kw) });
    if (cfg.type) rules.push({ c: 'tk-type', r: wordRe(cfg.type) });
    if (cfg.bi) rules.push({ c: 'tk-fn', r: wordRe(cfg.bi) });
    rules.push({ c: 'tk-fn', r: rx('[A-Za-z_$][\\w$]*(?=\\s*\\()') });
    rules.push({ c: 'tk-op', r: rx('[+\\-*/%=<>!&|^~?:]+') });
    rules.push({ c: 'tk-punc', r: rx('[{}()\\[\\];,.]') });
    rules.push({ c: 'tk-var', r: identRe() });
    return rules;
  }

  var CLike_KW = 'abstract assert async await break case catch class const continue '
    + 'debugger default delete do else enum export extends final finally for from function get '
    + 'if implements import in instanceof interface let native new of package private protected '
    + 'public return set static super switch this throw throws try typeof var void while with yield '
    + 'true false null undefined nil';
  var C_KW = 'auto break case catch class const constexpr continue default delete do else enum '
    + 'explicit export extern false for friend goto if inline mutable namespace new nullptr operator '
    + 'private protected public register return sizeof static struct switch template this throw true '
    + 'try typedef typename union using virtual void volatile while';
  var C_TYPE = 'bool char char16_t char32_t double float int long short signed size_t string '
    + 'unsigned wchar_t int8_t int16_t int32_t int64_t uint8_t uint16_t uint32_t uint64_t '
    + 'std vector map set unordered_map shared_ptr unique_ptr auto';
  var JAVA_KW = 'abstract assert break case catch class const continue default do else enum extends '
    + 'final finally for goto if implements import instanceof interface native new package private '
    + 'protected public record return sealed static strictfp super switch synchronized this throw '
    + 'throws transient try var void volatile while yield true false null';
  var JAVA_TYPE = 'boolean byte char double float int long short String Integer Long Double Float '
    + 'Boolean Character Object List Map Set ArrayList HashMap HashSet Optional Stream';
  var CS_KW = 'abstract as async await base break case catch checked class const continue default '
    + 'delegate do else enum event explicit extern finally fixed for foreach get goto if implicit in '
    + 'interface internal is lock namespace new operator out override params private protected public '
    + 'readonly record ref return sealed set sizeof stackalloc static struct switch this throw try '
    + 'typeof unchecked unsafe using var virtual void volatile when where while yield true false null';
  var CS_TYPE = 'bool byte char decimal double dynamic float int long object sbyte short string '
    + 'uint ulong ushort Task List Dictionary IEnumerable';
  var PHP_KW = 'abstract and array as break callable case catch class clone const continue declare '
    + 'default do echo else elseif empty enddeclare endfor endforeach endif endswitch endwhile enum '
    + 'extends final finally fn for foreach function global goto if implements include include_once '
    + 'instanceof insteadof interface isset list match namespace new or print private protected public '
    + 'readonly require require_once return static switch throw trait try unset use var while xor yield '
    + 'true false null this self parent';
  var SQL_KW = 'add all alter and any as asc begin between by case cast check column commit constraint '
    + 'create cross database default delete desc distinct drop else end exists foreign from full group '
    + 'having if in index inner insert into is join key left like limit not null offset on or order '
    + 'outer primary references right rollback select set table then union unique update values view '
    + 'when where with';
  var SQL_TYPE = 'bigint binary bit blob boolean char date datetime decimal double float int integer '
    + 'json numeric real text time timestamp varchar';
  var GO_KW = 'break case chan const continue default defer else fallthrough for func go goto if '
    + 'import interface map package range return select struct switch type var true false nil iota';
  var GO_TYPE = 'bool byte complex64 complex128 error float32 float64 int int8 int16 int32 int64 '
    + 'rune string uint uint8 uint16 uint32 uint64 uintptr any';
  var RUST_KW = 'as async await break const continue crate dyn else enum extern false fn for if impl '
    + 'in let loop match mod move mut pub ref return self Self static struct super trait true type '
    + 'unsafe use where while yield';
  var RUST_TYPE = 'bool char f32 f64 i8 i16 i32 i64 i128 isize str String u8 u16 u32 u64 u128 usize '
    + 'Vec Option Result Box Rc Arc HashMap HashSet';
  var BASH_KW = 'if then else elif fi for while until do done case esac function in select time '
    + 'return break continue export local readonly declare typeset unset shift source alias echo '
    + 'printf cd pwd exit test set trap eval exec sudo apt yum brew git npm yarn pnpm pip python '
    + 'node docker kubectl make curl wget grep sed awk cat ls cp mv rm mkdir chmod chown';
  var RUBY_KW = 'alias and begin break case class def defined do else elsif end ensure for if in '
    + 'module next nil not or redo rescue retry return self super then true false undef unless until '
    + 'when while yield require attr_accessor puts print lambda proc';
  var SWIFT_KW = 'actor associatedtype async await break case catch class continue default defer deinit '
    + 'do else enum extension fallthrough false fileprivate for func guard if import in init inout '
    + 'internal is lazy let nil open operator private protocol public repeat rethrows return self Self '
    + 'static struct subscript super switch throw throws true try typealias var where while';
  var KOTLIN_KW = 'abstract actual annotation as break by catch class companion const constructor '
    + 'continue crossinline data delegate do dynamic else enum expect external final finally for fun '
    + 'get if import in infix init inline inner interface internal is lateinit noinline null object '
    + 'open operator out override package private protected public reified return sealed set super '
    + 'suspend tailrec this throw try typealias val var vararg when where while true false';
  var INI_RE = rx('^[ \\t]*\\[[^\\]\\n]*\\]');

  var RULES = {
    javascript: buildRules({
      comment: CMT_SLASH, str: alt(STR_BT, STR_DQ, STR_SQ),
      kw: CLike_KW + ' interface type enum declare namespace abstract readonly keyof infer never unknown any',
      type: 'Array Boolean Date Error Function JSON Map Math Number Object Promise RegExp Set String '
        + 'Symbol WeakMap BigInt console window document globalThis process require module exports',
    }),
    json: [
      { c: 'tk-key', r: rx('"(?:\\\\.|[^"\\\\\\n])*"(?=\\s*:)') },
      { c: 'tk-str', r: STR_DQ },
      { c: 'tk-kw', r: wordRe('true false null') },
      { c: 'tk-num', r: NUM_RE },
      { c: 'tk-punc', r: rx('[{}()\\[\\]:,]') },
    ],
    yaml: [
      { c: 'tk-com', r: CMT_HASH },
      { c: 'tk-key', r: rx('(?<=^(?:[ \\t]*-?[ \\t]*)?)[\\w.$\\-\\/]+(?=[ \\t]*:(?![\\/]))') },
      { c: 'tk-str', r: alt(STR_DQ, STR_SQ) },
      { c: 'tk-kw', r: wordRe('true false null yes no on off') },
      { c: 'tk-num', r: NUM_RE },
      { c: 'tk-op', r: rx('[\\-?*&|><!%@`]') },
      { c: 'tk-punc', r: rx('[:{}\\[\\],]') },
      { c: 'tk-var', r: rx('[^\\s:{}#\\[\\],]+') },
    ],
    markdown: [
      { c: 'tk-str', r: rx('^(?: {4}|\\t)[^\\n]*') },
      { c: 'tk-str', r: rx('```[^\\n]*\\n[\\s\\S]*?\\n?```|~~~[^\\n]*\\n[\\s\\S]*?\\n?~~~') },
      { c: 'tk-kw', r: rx('^#{1,6}[^\\n]*') },
      { c: 'tk-anno', r: rx('^[ \\t]*>[^\\n]*') },
      { c: 'tk-key', r: rx('^[ \\t]*(?:[-*+]|\\d+\\.)[ \\t]') },
      { c: 'tk-op', r: rx('^[ \\t]*(?:-{3,}|={3,}|\\*{3,})[ \\t]*$') },
      { c: 'tk-kw', r: rx('\\*\\*[^*\\n]+\\*\\*|__[^_\\n]+__') },
      { c: 'tk-str', r: rx('`[^`\\n]+`') },
      { c: 'tk-com', r: rx('(?<!\\*)\\*[^*\\n]+\\*|(?<!_)_[^_\\n]+_') },
      { c: 'tk-fn', r: rx('!?\\[[^\\]\\n]*\\]\\([^)\\n]*\\)') },
      { c: 'tk-punc', r: rx('[\\[\\]()#*>|`~_-]') },
    ],
    css: [
      { c: 'tk-com', r: rx('\\/\\*[\\s\\S]*?\\*\\/') },
      { c: 'tk-str', r: alt(STR_DQ, STR_SQ) },
      { c: 'tk-kw', r: rx('@[\\w-]+') },
      { c: 'tk-type', r: rx('[.#][A-Za-z_][\\w-]*|&|::?[a-z-]+') },
      { c: 'tk-key', r: rx('[a-zA-Z-]+(?=\\s*:)') },
      { c: 'tk-num', r: rx('#[0-9a-fA-F]{3,8}|-?\\d*\\.?\\d+(?:px|em|rem|%|vh|vw|s|ms|deg|fr|pt|ch|vmin|vmax)?') },
      { c: 'tk-fn', r: rx('[a-zA-Z-]+(?=\\()') },
      { c: 'tk-punc', r: rx('[{}();:,]') },
      { c: 'tk-var', r: rx('[a-zA-Z_][\\w-]*') },
    ],
    html: [
      { c: 'tk-com', r: rx('<!--[\\s\\S]*?-->') },
      { c: 'tk-anno', r: rx('<!DOCTYPE[^>]*>|<\\?[\\s\\S]*?\\?>') },
      { c: 'tk-tag', r: rx('&lt;\\/?[A-Za-z][\\w:-]*|\\/?&gt;') },
      { c: 'tk-tag', r: rx('<\\/?[A-Za-z][\\w:-]*|\\/?>') },
      { c: 'tk-attr', r: rx('[A-Za-z_:][-\\w:.]*(?=\\s*=)') },
      { c: 'tk-str', r: alt(STR_DQ, STR_SQ) },
      { c: 'tk-op', r: rx('=') },
      { c: 'tk-var', r: rx('[A-Za-z_][\\w-]*') },
    ],
    bash: [
      { c: 'tk-com', r: CMT_HASH },
      { c: 'tk-str', r: alt(STR_DQ, STR_SQ, STR_BT) },
      { c: 'tk-var', r: rx('\\$\\{[^}]*\\}|\\$[A-Za-z_][\\w]*|\\$[?#@*!$0-9]') },
      { c: 'tk-kw', r: wordRe(BASH_KW) },
      { c: 'tk-num', r: NUM_RE },
      { c: 'tk-anno', r: rx('(?:^|\\s)--?[\\w-]+') },
      { c: 'tk-op', r: rx('[|&><=!]+') },
      { c: 'tk-punc', r: rx('[{}()\\[\\];,]') },
      { c: 'tk-var', r: rx('[\\w./-]+') },
    ],
    sql: buildRules({
      comment: alt(CMT_DASH, rx('\\/\\*[\\s\\S]*?\\*\\/')), str: alt(STR_SQ, STR_DQ),
      kw: SQL_KW, type: SQL_TYPE,
      bi: 'count sum avg min max coalesce cast now date_part extract round abs length upper lower trim',
    }),
    diff: [
      { c: 'tk-key', r: rx('^@@[^\\n]*') },
      { c: 'tk-ins', r: rx('^\\+[^\\n]*') },
      { c: 'tk-del', r: rx('^-[^\\n]*') },
      { c: 'tk-anno', r: rx('^(?:diff|index|new file|deleted file|similarity)[^\\n]*') },
      { c: 'tk-com', r: rx('^[^\\n]+') },
    ],
    ini: [
      { c: 'tk-com', r: rx('[;#][^\\n]*') },
      { c: 'tk-kw', r: INI_RE },
      { c: 'tk-key', r: rx('^[ \\t]*[\\w.$-]+(?=[ \\t]*=)') },
      { c: 'tk-op', r: rx('=') },
      { c: 'tk-str', r: rx('[^\\n=]+') },
    ],
    dockerfile: [
      { c: 'tk-com', r: CMT_HASH },
      { c: 'tk-kw', r: rx('(?<=^|\\n)[ \\t]*(?:FROM|RUN|CMD|LABEL|MAINTAINER|EXPOSE|ENV|ADD|COPY|ENTRYPOINT|VOLUME|USER|WORKDIR|ARG|ONBUILD|STOPSIGNAL|HEALTHCHECK|SHELL|AS)\\b') },
      { c: 'tk-str', r: alt(STR_DQ, STR_SQ) },
      { c: 'tk-num', r: NUM_RE },
      { c: 'tk-var', r: rx('\\$\\{[^}]*\\}|\\$\\w+') },
      { c: 'tk-op', r: rx('--?[\\w-]+') },
      { c: 'tk-var', r: rx('[^\\s]+') },
    ],
    makefile: [
      { c: 'tk-com', r: CMT_HASH },
      { c: 'tk-kw', r: rx('(?<=^|\\n)(?:[A-Za-z_][\\w.-]*)(?=[ \\t]*:)') },
      { c: 'tk-var', r: rx('\\$\\([^)]*\\)|\\$\\{[^}]*\\}|\\$\\w') },
      { c: 'tk-fn', r: rx('\\.PHONY|\\.DEFAULT|\\.SUFFIXES') },
      { c: 'tk-op', r: rx('[:=+?]+') },
      { c: 'tk-var', r: rx('[^\\s]+') },
    ],
    plaintext: null,
    text: null,
  };

  (function registerWordLangs() {
    function reg(names, cfg) {
      var rules = buildRules(cfg);
      names.split(' ').forEach(function (n) { RULES[n] = rules; });
    }
    reg('typescript ts tsx jsx', {
      comment: CMT_SLASH, str: alt(STR_BT, STR_DQ, STR_SQ),
      kw: CLike_KW + ' interface type enum declare namespace abstract readonly keyof infer never unknown any',
      type: 'Array Boolean Date Error Function JSON Map Math Number Object Promise RegExp Set String '
        + 'Symbol WeakMap BigInt console window document globalThis',
    });
    reg('c cpp c++ h hpp objc', {
      comment: CMT_SLASH, str: alt(STR_DQ, STR_SQ), pre: rx('(?<=^|\\n)[ \\t]*#[ \\t]*\\w+'),
      kw: C_KW, type: C_TYPE,
    });
    reg('java kotlin kt scala groovy gradle', {
      comment: CMT_SLASH, str: alt(STR_TRIPLE, STR_DQ, STR_SQ), anno: rx('@[A-Za-z_][\\w.]*'),
      kw: JAVA_KW + ' ' + KOTLIN_KW, type: JAVA_TYPE + ' Int Double Float Long Short Byte Boolean Any Unit Nothing',
    });
    reg('csharp cs', {
      comment: CMT_SLASH, str: alt(STR_DQ, STR_SQ), anno: rx('@[A-Za-z_][\\w]*|\\[[A-Z][\\w.]*\\]'),
      kw: CS_KW, type: CS_TYPE,
    });
    reg('php', {
      comment: alt(CMT_SLASH, CMT_HASH), str: alt(STR_DQ, STR_SQ),
      kw: PHP_KW, type: 'int float string bool array object callable iterable void mixed',
    });
    reg('python py python3', {
      comment: CMT_HASH, str: alt(STR_TRIPLE, STR_DQ, STR_SQ), anno: rx('@[A-Za-z_][\\w.]*'),
      kw: 'and as assert async await break class continue def del elif else except finally for from '
        + 'global if import in is lambda nonlocal not or pass raise return try while with yield '
        + 'True False None self cls match case',
      type: 'bool bytes bytearray complex dict float frozenset int list object set str tuple type',
      bi: 'print len range open enumerate zip map filter sorted sum min max abs round isinstance '
        + 'issubclass super getattr setattr hasattr repr format input int float str list dict set tuple',
    });
    reg('go golang', {
      comment: CMT_SLASH, str: alt(STR_BT, STR_DQ, STR_SQ),
      kw: GO_KW, type: GO_TYPE,
      bi: 'make new len cap append copy delete panic recover print println close',
    });
    reg('rust rs', {
      comment: CMT_SLASH, str: alt(STR_DQ, STR_SQ), anno: rx('(?<=^|\\s)#!?\\[[^\\]]*\\]'),
      kw: RUST_KW, type: RUST_TYPE,
      bi: 'vec println format write panic assert assert_eq Some None Ok Err',
    });
    reg('ruby rb', {
      comment: CMT_HASH, str: alt(STR_DQ, STR_SQ),
      kw: RUBY_KW, type: 'Array Hash String Symbol Integer Float Range Proc',
    });
    reg('swift', {
      comment: CMT_SLASH, str: alt(STR_DQ, STR_SQ), anno: rx('@[A-Za-z_][\\w]*'),
      kw: SWIFT_KW, type: 'Int Double Float String Bool Array Dictionary Set Optional Any AnyObject',
    });
  }());

  var LANG_ALIAS = {
    js: 'javascript', mjs: 'javascript', cjs: 'javascript', node: 'javascript',
    ts: 'typescript', tsx: 'typescript', jsx: 'javascript',
    py: 'python', python3: 'python',
    sh: 'bash', shell: 'bash', zsh: 'bash', console: 'bash', powershell: 'bash', ps1: 'bash',
    'c++': 'cpp', cc: 'cpp', cxx: 'cpp', hpp: 'cpp', 'c#': 'csharp', cs: 'csharp',
    yml: 'yaml', md: 'markdown', mkd: 'markdown',
    svg: 'html', xml: 'html', vue: 'html', htm: 'html',
    scss: 'css', less: 'css', sass: 'css', stylus: 'css',
    toml: 'ini', conf: 'ini', cfg: 'ini', properties: 'ini', env: 'ini',
    docker: 'dockerfile', make: 'makefile', mk: 'makefile', patch: 'diff',
    txt: 'text', plain: 'text', none: 'text',
  };

  /** 语言归一：把常见别名收敛成规则表里的键。 */
  function normLang(lang) {
    var k = String(lang || '').trim().toLowerCase();
    if (!k) return 'text';
    if (RULES[k] !== undefined) return k;
    if (LANG_ALIAS[k]) return LANG_ALIAS[k];
    return 'text';
  }

  function rulesFor(lang) {
    var key = normLang(lang);
    return RULES[key] || null;
  }

  function highlightLines(code, lang) {
    var src = String(code === null || code === undefined ? '' : code);
    var raw = src.split('\n');
    var rules = rulesFor(lang);
    if (!rules) return raw.map(esc);
    var toks = tokenize(src, rules);
    var lines = [[]];
    for (var i = 0; i < toks.length; i++) {
      var segs = toks[i].t.split('\n');
      for (var j = 0; j < segs.length; j++) {
        if (j > 0) lines.push([]);
        if (segs[j]) lines[lines.length - 1].push({ t: segs[j], c: toks[i].c });
      }
    }
    while (lines.length < raw.length) lines.push([]);
    return lines.map(function (line) {
      return line.map(function (s) {
        return s.c ? '<span class="' + s.c + '">' + esc(s.t) + '</span>' : esc(s.t);
      }).join('');
    });
  }

  function highlight(code, lang) {
    return highlightLines(code, lang).join('\n');
  }

  ACRender.highlight = highlight;
  ACRender.highlightLines = highlightLines;
  ACRender.normLang = normLang;
  ACRender.codeBlock = codeBlock;

  // ---------------------------------------------------------------- 代码块
  /** 把 "3,5-7" 这类行号描述解析成 {行号: true}。 */
  function parseRanges(spec) {
    var set = {};
    String(spec === null || spec === undefined ? '' : spec).split(/[,，;；\s]+/).forEach(function (part) {
      var m = /^(\d+)\s*(?:[-~]\s*(\d+))?$/.exec(part.trim());
      if (!m) return;
      var a = parseInt(m[1], 10);
      var b = m[2] ? parseInt(m[2], 10) : a;
      if (b < a) { var t = a; a = b; b = t; }
      if (b - a > 400) b = a + 400;
      for (var i = a; i <= b; i++) set[i] = true;
    });
    return set;
  }

  /**
   * 代码块的结构化样式（IR 形态）：颜色默认值只写在 tokens.js，字号 / 内边距 / 圆角的默认
   * 值也只写这一处 —— HTML 渲染与 PPTX 写出（export.py 的 _code_vars）都读同一份，不再各
   * 写一套「深色卡片大概是 #1f2430」这样的猜测值。
   */
  function codeVars(props) {
    var p = props || {};
    var theme = (p.theme || 'dark') !== 'light' ? 'dark' : 'light';
    var bg = safeColor(p.bgColor, '');
    var fg = safeColor(p.fgColor, '');
    var accent = safeColor(p.accent, '');
    return {
      theme: theme,
      hasBg: !!bg,
      hasFg: !!fg,
      hasAccent: !!accent,
      bg: bg || tok('code', theme, 'bg'),
      bar: bg || tok('code', theme, 'bar'),
      fg: fg || tok('code', theme, 'fg'),
      accent: accent || tok('code', theme, 'accent'),
      fontSize: clamp(num(p.fontSize, 13), 6, 96),
      lineHeight: clamp(num(p.lineHeight, 1.55), 1, 4),
      padding: clamp(num(p.padding, 10), 0, 80),
      radius: clamp(num(p.radius, 8), 0, 40),
      shadow: !!p.shadow,
    };
  }

  ACRender.codeVars = codeVars;

  /**
   * CSDN 风格代码框：外框 + 标题栏（圆点 / 标题 / 语言徽标）+ 行号槽 + 语法高亮 + 高亮行。
   * 没有复制按钮 —— 导出走截图，按钮只会污染画面。
   */
  function codeBlock(props) {
    var p = props || {};
    var v = codeVars(p);
    var dark = v.theme === 'dark';
    var code = String(p.code === null || p.code === undefined ? '' : p.code);
    var fontSize = v.fontSize;
    var showBar = p.showBar !== false;
    var isEmpty = code.trim() === '';
    var showLn = p.lineNumbers !== false && p.lineNumbers !== 0 && !isEmpty;
    var rawLang = String(p.lang || '').trim();
    var label = (p.langLabel === false || !rawLang) ? '' : rawLang.toUpperCase();

    var vars = [
      '--ac-fs:' + fontSize + 'px',
      '--ac-lh:' + v.lineHeight,
      '--ac-lh-em:' + (fontSize * v.lineHeight).toFixed(2) + 'px',
      '--ac-pad:' + v.padding + 'px',
      '--ac-tab:' + clamp(num(p.tabSize, 4), 1, 12),
      // 字族里的引号必须写成实体：这段字符串经 innerHTML 落地，裸引号会提前闭合 style 属性，
      // 后面所有自定义属性（bg / fg / accent / radius / shadow）会被吞掉
      '--ac-font:Consolas,&#39;Courier New&#39;,ui-monospace,monospace',
      '--ac-radius:' + v.radius + 'px',
      '--ac-shadow:' + (v.shadow ? shadowCss(tok('shadow', 'code')) : 'none'),
    ];
    if (p.wrap) vars.push('--ac-wrap:pre-wrap');
    if (v.hasBg) { vars.push('--ac-bg:' + v.bg); vars.push('--ac-bar:' + v.bar); }
    if (v.hasFg) vars.push('--ac-fg:' + v.fg);
    if (v.hasAccent) vars.push('--ac-accent:' + v.accent);

    var head = '<div class="ac-code" data-theme="' + (dark ? 'dark' : 'light') + '"'
      + (v.shadow ? '' : ' data-shadow="0"')
      + ' style="' + vars.join(';') + '">';

    var bar = '';
    if (showBar) {
      var plain = p.macStyle === false;
      bar = '<div class="ac-code-bar' + (plain ? '' : ' is-mac') + '">'
        + '<span class="ac-dots' + (plain ? ' is-plain' : '') + '"><i></i><i></i><i></i></span>'
        + '<span class="ac-code-title">' + esc(p.title || '') + '</span>'
        + (label ? '<span class="ac-code-lang">' + esc(label) + '</span>' : '')
        + '</div>';
    }

    var scrollOpen = '<div class="ac-code-scroll"><pre class="ac-code-pre">';
    if (isEmpty) {
      return head + bar + '<div class="ac-code-body">' + scrollOpen
        + '<code class="ac-code-empty">' + esc(p.placeholder || '空代码块：在右侧属性面板粘贴代码') + '</code>'
        + '</pre></div></div>';
    }

    var lines = highlightLines(code, rawLang);
    var start = Math.max(-9999, Math.min(99999, Math.round(num(p.startLine, 1))));
    var hl = parseRanges(p.highlightLines);
    var rows = '';
    var nums = '';
    for (var i = 0; i < lines.length; i++) {
      var isHl = hl[start + i] ? ' is-hl' : '';
      rows += '<span class="ac-code-row' + isHl + '">' + lines[i] + '</span>';
      if (showLn) nums += '<span class="' + isHl.trim() + '">' + (start + i) + '</span>';
    }
    var gutter = showLn ? '<div class="ac-code-gutter">' + nums + '</div>' : '';
    return head + bar + '<div class="ac-code-body">' + gutter
      + scrollWrap(rows) + '</div></div>';
  }

  function scrollWrap(rows) {
    return '<div class="ac-code-scroll"><pre class="ac-code-pre"><code>' + rows + '</code></pre></div>';
  }

  // ---------------------------------------------------------------- LaTeX 公式
  /* 不引 KaTeX / MathJax（宿主零依赖），手写一个覆盖常用记号的小渲染器。
   * 输出纯 HTML + CSS 变量着色，浏览器渲染什么样，截图导出就是什么样（不失真）。 */

  var TEX_SYM = {
    alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ϵ', varepsilon: 'ε', zeta: 'ζ',
    eta: 'η', theta: 'θ', vartheta: 'ϑ', iota: 'ι', kappa: 'κ', varkappa: 'ϰ', lambda: 'λ',
    mu: 'μ', nu: 'ν', xi: 'ξ', pi: 'π', varpi: 'ϖ', rho: 'ρ', varrho: 'ϱ', sigma: 'σ',
    varsigma: 'ς', tau: 'τ', upsilon: 'υ', phi: 'ϕ', varphi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω',
    Gamma: 'Γ', Delta: 'Δ', Theta: 'Θ', Lambda: 'Λ', Xi: 'Ξ', Pi: 'Π', Sigma: 'Σ',
    Upsilon: 'Υ', Phi: 'Φ', Psi: 'Ψ', Omega: 'Ω',
    times: '×', div: '÷', pm: '±', mp: '∓', cdot: '⋅', ast: '∗', star: '⋆', circ: '∘', bullet: '∙',
    le: '≤', leq: '≤', ge: '≥', geq: '≥', ne: '≠', neq: '≠', approx: '≈', equiv: '≡', cong: '≅',
    sim: '∼', simeq: '≃', propto: '∝', ll: '≪', gg: '≫', prec: '≺', succ: '≻', subset: '⊂',
    subseteq: '⊆', supset: '⊃', supseteq: '⊇', in: '∈', notin: '∉', ni: '∋', cup: '∪', cap: '∩',
    setminus: '∖', emptyset: '∅', varnothing: '∅', forall: '∀', exists: '∃', nexists: '∄',
    neg: '¬', lnot: '¬', land: '∧', wedge: '∧', lor: '∨', vee: '∨', oplus: '⊕', otimes: '⊗',
    ominus: '⊖', odot: '⊙', to: '→', gets: '←', rightarrow: '→', leftarrow: '←',
    leftrightarrow: '↔', Rightarrow: '⇒', Leftarrow: '⇐', Leftrightarrow: '⇔', mapsto: '↦',
    implies: '⟹', iff: '⟺', uparrow: '↑', downarrow: '↓', partial: '∂', nabla: '∇', infty: '∞',
    ell: 'ℓ', hbar: 'ℏ', Re: 'ℜ', Im: 'ℑ', aleph: 'ℵ', angle: '∠', perp: '⊥', parallel: '∥',
    therefore: '∴', because: '∵', dots: '…', ldots: '…', cdots: '⋯', vdots: '⋮', ddots: '⋱',
    prime: '′', mid: '∣', nmid: '∤', degree: '°', checkmark: '✓', square: '□', triangle: '△',
    lbrace: '{', rbrace: '}', '{': '{', '}': '}', '|': '∣',
    langle: '⟨', rangle: '⟩', lfloor: '⌊', rfloor: '⌋', lceil: '⌈', rceil: '⌉',
    lvert: '|', rvert: '|', lVert: '‖', rVert: '‖', vert: '|', Vert: '‖', backslash: '\\',
    smallint: '∫', int: '∫', oint: '∮', iint: '∬', sum: '∑', prod: '∏', coprod: '∐',
    bigcup: '⋃', bigcap: '⋂', bigoplus: '⨁', bigotimes: '⨂', bigvee: '⋁', bigwedge: '⋀',
    lim: 'lim', limsup: 'lim sup', liminf: 'lim inf', max: 'max', min: 'min', sup: 'sup',
    inf: 'inf', argmax: 'arg max', argmin: 'arg min', deg: 'deg', gcd: 'gcd', sin: 'sin',
    cos: 'cos', tan: 'tan', cot: 'cot', sec: 'sec', csc: 'csc', log: 'log', ln: 'ln', lg: 'lg',
    exp: 'exp', det: 'det', dim: 'dim', ker: 'ker', mod: 'mod', bmod: 'mod', quad: '', qquad: '',
    updownarrow: '↕', Updownarrow: '⇕', longleftarrow: '⟵', longrightarrow: '⟶',
    longleftrightarrow: '⟷', Longleftarrow: '⟸', Longrightarrow: '⟹', Longleftrightarrow: '⟺',
    hookrightarrow: '↪', hookleftarrow: '↩', rightleftharpoons: '⇌', leftrightharpoons: '⇋',
    leadsto: '⇝', uplus: '⊎', sqcup: '⊔', sqcap: '⊓', vdash: '⊢', dashv: '⊣', models: '⊨',
    top: '⊤', bot: '⊥', asymp: '≍', doteq: '≐', bowtie: '⋈', smile: '⌣', frown: '⌢',
    wp: '℘', dagger: '†', ddagger: '‡', oslash: '⊘', bigcirc: '◯', Box: '□', Diamond: '◇',
    clubsuit: '♣', heartsuit: '♡', spadesuit: '♠', diamondsuit: '♢',
    flat: '♭', natural: '♮', sharp: '♯', '%': '%', '&': '&', '#': '#', '$': '$', '_': '_',
  };

  var TEX_BIG = {
    sum: 1, prod: 1, coprod: 1, bigcup: 1, bigcap: 1, bigoplus: 1, bigotimes: 1,
    bigvee: 1, bigwedge: 1, lim: 1, limsup: 1, liminf: 1, max: 1, min: 1, sup: 1, inf: 1,
    argmax: 1, argmin: 1, gcd: 1, det: 1,
  };

  /* 尺寸命令：\big \Big \bigg \Bigg（后面可跟 l / r / m），把紧随其后的定界符放大。
   * 值是按 1em 计的放大倍数，与 KaTeX 的视觉比例大致对齐。 */
  var TEX_SIZE = { big: 1.2, Big: 1.6, bigg: 1.9, Bigg: 2.2 };

  /** 返回尺寸倍数；不是尺寸命令（或不是尺寸命令的 l/r/m 变体）时返回 0。 */
  function texSizeFactor(name) {
    if (TEX_SIZE[name] !== undefined) return TEX_SIZE[name];
    if (/[lrm]$/.test(name) && TEX_SIZE[name.slice(0, -1)] !== undefined) return TEX_SIZE[name.slice(0, -1)];
    return 0;
  }

  var TEX_SPACE = {
    ',': '0.17em', ';': '0.28em', ':': '0.22em', '!': '-0.17em', ' ': '0.3em',
    quad: '1em', qquad: '2em', thinspace: '0.17em', medspace: '0.22em',
    thickspace: '0.28em', enspace: '0.5em', negthinspace: '-0.17em',
  };

  var TEX_ACCENT = {
    hat: '^', widehat: '^', bar: '¯', vec: '→', tilde: '~', widetilde: '~',
    dot: '˙', ddot: '¨', check: 'ˇ', breve: '˘', acute: '´', grave: '`',
    overrightarrow: '⟶', overleftarrow: '⟵', overleftrightarrow: '⟷',
  };

  var TEX_DOUBLE = {
    A: '𝔸', B: '𝔹', C: 'ℂ', D: '𝔻', E: '𝔼', F: '𝔽', G: '𝔾', H: 'ℍ', I: '𝕀', J: '𝕁',
    K: '𝕂', L: '𝕃', M: '𝕄', N: 'ℕ', O: '𝕆', P: 'ℙ', Q: 'ℚ', R: 'ℝ', S: '𝕊', T: '𝕋',
    U: '𝕌', V: '𝕍', W: '𝕎', X: '𝕏', Y: '𝕐', Z: 'ℤ',
  };

  /* 关系符 / 二元运算符：手工渲染没有 TeX 的原子间距，靠 CSS margin 补回来，
   * 否则相邻的字母、根号、等号会挤在一起甚至互相覆盖。 */
  var TEX_REL_CH = '=<>≤≥≠≈≡≅∼≃∝≪≫≺≻⊂⊆⊃⊇∈∉∋→←↔⇒⇐⇔↦⟹⟺⟵⟶⟷↪↩⇌⇋⇝⊢⊣⊨∣∤∴∵↑↓↕⇕';
  var TEX_OP_CH = '×÷±∓⋅∗⋆∘∙∪∩⊕⊗⊖⊙∖⊎⊔⊓⋈∧∨';
  var TEX_PUNCT_CH = ',;';

  /** 前一个非空白字符是否是「操作数结尾」；用于把 + - * 区分为二元/一元运算符。 */
  function isBinContext(src, i) {
    var k = i - 1;
    while (k >= 0 && src.charAt(k) === ' ') k -= 1;
    if (k < 0) return false;
    var pc = src.charAt(k);
    if (pc === '}' || pc === ')' || pc === ']' || pc === '|') return true;
    return /[A-Za-z0-9.'!]/.test(pc);
  }

  /** 深度感知切分：只在括号层级为 0 处切开。 */
  function splitTop(src, delim) {
    var out = [];
    var buf = '';
    var depth = 0;
    var i = 0;
    var d0 = delim.charAt(0);
    while (i < src.length) {
      var ch = src.charAt(i);
      if (ch === '\\') {
        if (d0 === '\\' && src.substr(i, delim.length) === delim) {
          out.push(buf); buf = ''; i += delim.length; continue;
        }
        buf += src.substr(i, 2); i += 2; continue;
      }
      if (ch === '{') depth += 1;
      else if (ch === '}') depth -= 1;
      if (depth <= 0 && ch === d0) { out.push(buf); buf = ''; i += 1; continue; }
      buf += ch; i += 1;
    }
    out.push(buf);
    return out;
  }

  /** 读取一个 {…} 组，返回 {text, next}；调用点保证前面的空白已跳过。 */
  function texBrace(src, i) {
    var n = src.length;
    while (i < n && src.charAt(i) === ' ') i += 1;
    if (src.charAt(i) !== '{') return { text: '', next: i };
    var depth = 0;
    var start = i + 1;
    var j = i;
    for (; j < n; j += 1) {
      var c = src.charAt(j);
      if (c === '\\') { j += 1; continue; }
      if (c === '{') depth += 1;
      else if (c === '}') { depth -= 1; if (depth === 0) break; }
    }
    return { text: src.slice(start, Math.min(j, n)), next: Math.min(j + 1, n) };
  }

  function texAtoms(atoms) {
    var out = '';
    for (var i = 0; i < atoms.length; i++) {
      var a = atoms[i];
      if (a.brace) {
        // \underbrace{X}_{lab} / \overbrace{X}^{lab}：花括号随内容伸缩，标签居中
        var hook = '<span class="tx-br-hook' + (a.brace === 'over' ? ' tx-br-up' : '') + '"></span>';
        var body = '<span class="tx-br-body">' + a.html + '</span>';
        var up = a.sup ? '<span class="tx-br-lab">' + a.sup + '</span>' : '';
        var dn = a.sub ? '<span class="tx-br-lab">' + a.sub + '</span>' : '';
        out += '<span class="tx-br">'
          + (a.brace === 'over' ? up + hook + body + dn : up + body + hook + dn)
          + '</span>';
        continue;
      }
      if (!a.sup && !a.sub) { out += a.html; continue; }
      if (a.big) {
        out += '<span class="tx-big">'
          + (a.sup ? '<span class="tx-lim tx-lim-up">' + a.sup + '</span>' : '')
          + '<span class="tx-big-op">' + a.html + '</span>'
          + (a.sub ? '<span class="tx-lim tx-lim-dn">' + a.sub + '</span>' : '')
          + '</span>';
      } else {
        // 只有上标要整体抬高、只有下标要整体压低；两者都有时列内自然堆叠
        var scr = a.sup && a.sub ? ' tx-scr-b' : (a.sup ? ' tx-scr-up' : ' tx-scr-dn');
        out += a.html + '<span class="tx-scr' + scr + '">'
          + (a.sup ? '<span class="tx-sup">' + a.sup + '</span>' : '')
          + (a.sub ? '<span class="tx-sub">' + a.sub + '</span>' : '')
          + '</span>';
      }
    }
    return out;
  }

  /** 解析一段公式（遇到 } 或顶层 & / \\ 停），返回原子序列。 */
  function texSeq(src, pos) {
    var atoms = [];
    var i = pos;
    var n = src.length;
    while (i < n) {
      var ch = src.charAt(i);
      if (ch === '}') break;
      if (ch === '&') break;
      if (ch === '\\' && src.charAt(i + 1) === '\\') break;
      if (ch === '^' || ch === '_') {
        var g = texArg(src, i + 1);
        var target = atoms.length ? atoms[atoms.length - 1] : { html: '', big: false };
        if (!atoms.length) atoms.push(target);
        if (ch === '^') target.sup = g.html; else target.sub = g.html;
        i = g.next;
        continue;
      }
      var atom = texAtom(src, i);
      atoms.push(atom.node);
      i = atom.next;
    }
    return { atoms: atoms, next: i };
  }

  /** 取一个参数：{…} 组 / 单条命令 / 单个字符。 */
  function texArg(src, i) {
    var n = src.length;
    while (i < n && src.charAt(i) === ' ') i += 1;
    if (i >= n) return { html: '', next: i };
    if (src.charAt(i) === '{') {
      var g = texBrace(src, i);
      return { html: texAtoms(texSeq(g.text, 0).atoms), next: g.next };
    }
    if (src.charAt(i) === '\\') {
      var c = texCmd(src, i);
      return { html: texAtoms([c.node]), next: c.next };
    }
    return { html: esc(src.charAt(i)), next: i + 1 };
  }

  function texAtom(src, i) {
    var ch = src.charAt(i);
    if (ch === '{') {
      var g = texArg(src, i);
      return { node: { html: g.html }, next: g.next };
    }
    if (ch === '\\') {
      var c = texCmd(src, i);
      return { node: c.node, next: c.next };
    }
    if (ch === '~') return { node: { html: '<span class="tx-sp" style="width:.3em"></span>' }, next: i + 1 };
    if (ch === ' ') return { node: { html: ' ' }, next: i + 1 };
    if (/[A-Za-z]/.test(ch)) return { node: { html: '<span class="tx-ital">' + ch + '</span>' }, next: i + 1 };
    if (TEX_REL_CH.indexOf(ch) >= 0) return { node: { html: '<span class="tx-rel">' + esc(ch) + '</span>' }, next: i + 1 };
    if (TEX_OP_CH.indexOf(ch) >= 0) return { node: { html: '<span class="tx-op">' + esc(ch) + '</span>' }, next: i + 1 };
    if ((ch === '+' || ch === '-' || ch === '*') && isBinContext(src, i)) {
      return { node: { html: '<span class="tx-op">' + esc(ch) + '</span>' }, next: i + 1 };
    }
    if (TEX_PUNCT_CH.indexOf(ch) >= 0) return { node: { html: '<span class="tx-punc">' + esc(ch) + '</span>' }, next: i + 1 };
    return { node: { html: esc(ch) }, next: i + 1 };
  }

  function texCommand(name, src, next) {
    if (name === 'frac' || name === 'dfrac' || name === 'tfrac') {
      var a = texArg(src, next); var b = texArg(src, a.next);
      return { node: { html: '<span class="tx-frac"><span class="tx-frac-n">' + a.html
        + '</span><span class="tx-frac-d">' + b.html + '</span></span>' }, next: b.next };
    }
    if (name === 'sqrt') {
      var j = next;
      while (j < src.length && src.charAt(j) === ' ') j += 1;
      var idx = '';
      if (src.charAt(j) === '[') {
        var close = src.indexOf(']', j);
        if (close > 0) {
          idx = '<span class="tx-sqrt-idx">' + texAtoms(texSeq(src.slice(j + 1, close), 0).atoms) + '</span>';
          j = close + 1;
        }
      }
      var body = texArg(src, j);
      // 根号符号：小钩（.tx-sqrt-hook）固定尺寸负责左下折角，主杆（.tx-sqrt-bar）负责拉伸。
      // 钩的右臂顶部是一段竖直笔画 (25,16)->(25,1)，x 与主杆 (left:.25em) 完全同线，
      // 主杆底端 (bottom:.2em) 正好落在钩的拐点 (25,16) 上，因此两者永远无接缝、不脱节。
      var sym = '<span class="tx-sqrt-sym">'
        + '<span class="tx-sqrt-hook"><svg viewBox="0 0 30 36" preserveAspectRatio="none">'
        + '<path d="M1 17L11 34L25 16L25 1"/></svg></span>'
        + '<span class="tx-sqrt-bar"></span>'
        + '</span>';
      return { node: { html: '<span class="tx-sqrt">' + idx + sym
        + '<span class="tx-sqrt-body">' + body.html + '</span></span>' }, next: body.next };
    }
    if (name === 'text' || name === 'mbox' || name === 'textrm' || name === 'operatorname') {
      var t = texBrace(src, next);
      return { node: { html: '<span class="tx-txt">' + esc(t.text) + '</span>' }, next: t.next };
    }
    if (name === 'mathrm' || name === 'mathbf' || name === 'mathit' || name === 'mathsf'
      || name === 'mathtt' || name === 'mathfrak' || name === 'mathcal' || name === 'mathbb'
      || name === 'boldsymbol' || name === 'bm') {
      var inner = texArg(src, next);
      if (name === 'mathbb') inner = { html: texDoubleStruck(inner.html), next: inner.next };
      var cls = name === 'mathbf' || name === 'boldsymbol' || name === 'bm' ? 'tx-bf'
        : (name === 'mathcal' ? 'tx-cal' : (name === 'mathrm' || name === 'mathsf' || name === 'mathtt' ? 'tx-txt' : 'tx-ital'));
      return { node: { html: '<span class="' + cls + '">' + inner.html + '</span>' }, next: inner.next };
    }
    if (TEX_ACCENT[name]) {
      var acc = texArg(src, next);
      return { node: { html: '<span class="tx-acc"><span class="tx-acc-mk tx-acc-up">'
        + esc(TEX_ACCENT[name]) + '</span>' + acc.html + '</span>' }, next: acc.next };
    }
    if (name === 'overline') {
      var ov = texArg(src, next);
      return { node: { html: '<span style="text-decoration:overline">' + ov.html + '</span>' }, next: ov.next };
    }
    if (name === 'underline') {
      var ul = texArg(src, next);
      return { node: { html: '<span style="text-decoration:underline">' + ul.html + '</span>' }, next: ul.next };
    }
    if (name === 'underbrace' || name === 'overbrace') {
      var br = texArg(src, next);
      // 标签由紧随其后的 _{…} / ^{…} 提供，交给 texAtoms 摆到花括号外侧
      return { node: { html: br.html, brace: name === 'overbrace' ? 'over' : 'under' }, next: br.next };
    }
    if (name === 'xrightarrow' || name === 'xleftarrow' || name === 'xleftrightarrow'
      || name === 'xRightarrow' || name === 'xLeftarrow' || name === 'xLeftrightarrow') {
      var xj = next;
      var xbelow = '';
      while (xj < src.length && src.charAt(xj) === ' ') xj += 1;
      if (src.charAt(xj) === '[') {
        var xcl = src.indexOf(']', xj);
        if (xcl > 0) {
          xbelow = texAtoms(texSeq(src.slice(xj + 1, xcl), 0).atoms);
          xj = xcl + 1;
        }
      }
      var xa = texArg(src, xj);
      var arrow = name === 'xleftarrow' || name === 'xLeftarrow' ? '⟵'
        : (name === 'xleftrightarrow' || name === 'xLeftrightarrow' ? '⟷'
          : (name === 'xRightarrow' ? '⟹' : '⟶'));
      return { node: { html: '<span class="tx-xa"><span class="tx-xa-lab">' + xa.html + '</span>'
        + '<span class="tx-xa-ar">' + arrow + '</span>'
        + (xbelow ? '<span class="tx-xa-lab">' + xbelow + '</span>' : '')
        + '</span>' }, next: xa.next };
    }
    if (name === 'stackrel' || name === 'overset' || name === 'underset') {
      var s1 = texArg(src, next);
      var s2 = texArg(src, s1.next);
      var stop = name === 'underset' ? s2.html : s1.html;
      var sbot = name === 'underset' ? s1.html : s2.html;
      return { node: { html: '<span class="tx-st"><span class="tx-st-top">' + stop + '</span>'
        + sbot + '</span>' }, next: s2.next };
    }
    if (name === 'binom' || name === 'dbinom' || name === 'tbinom') {
      var bn = texArg(src, next);
      var bk = texArg(src, bn.next);
      return { node: { html: '<span class="tx-bin"><span class="tx-delim">(</span>'
        + '<span class="tx-frac"><span class="tx-frac-n">' + bn.html + '</span>'
        + '<span class="tx-frac-d">' + bk.html + '</span></span>'
        + '<span class="tx-delim">)</span></span>' }, next: bk.next };
    }
    if (name === 'color' || name === 'textcolor') {
      var cn = texBrace(src, next);
      var cbody = texArg(src, cn.next);
      var cc = safeColor(cn.text.trim(), '') || 'currentColor';
      return { node: { html: '<span style="color:' + escAttr(cc) + '">' + cbody.html + '</span>' }, next: cbody.next };
    }
    if (name === 'left' || name === 'right') {
      var k = next;
      while (k < src.length && src.charAt(k) === ' ') k += 1;
      if (src.charAt(k) === '.') k += 1;
      return { node: { html: '' }, next: k };
    }
    if (name === 'begin') return texEnvironment(src, next);
    var sizeFactor = texSizeFactor(name);
    if (sizeFactor) {
      // 只放大紧跟其后的那一个定界符（LaTeX 语义），后面内容不受影响
      var delim = texArg(src, next);
      return { node: { html: '<span class="tx-delim" style="font-size:' + sizeFactor + 'em">'
        + delim.html + '</span>' }, next: delim.next };
    }
    if (TEX_SPACE[name] !== undefined) {
      var w = TEX_SPACE[name];
      var style = w.charAt(0) === '-' ? 'margin-left:' + w : 'width:' + w;
      return { node: { html: '<span class="tx-sp" style="' + style + '"></span>' }, next: next };
    }
    if (name === 'limits' || name === 'nolimits' || name === 'displaystyle'
      || name === 'textstyle' || name === 'scriptstyle' || name === 'displaystyle '
      || name === 'nonumber' || name === 'notag' || name === 'label' || name === 'tag') {
      if (name === 'label' || name === 'tag') {
        var lab = texBrace(src, next);
        return { node: { html: '' }, next: lab.next };
      }
      return { node: { html: '' }, next: next };
    }
    if (TEX_SYM[name] !== undefined) {
      var sv = TEX_SYM[name];
      var shtml = esc(sv);
      if (sv.length === 1 && TEX_REL_CH.indexOf(sv) >= 0) shtml = '<span class="tx-rel">' + esc(sv) + '</span>';
      else if (sv.length === 1 && TEX_OP_CH.indexOf(sv) >= 0) shtml = '<span class="tx-op">' + esc(sv) + '</span>';
      return { node: { html: shtml, big: !!TEX_BIG[name] }, next: next };
    }
    return { node: { html: '<span class="tk-err">\\' + esc(name) + '</span>' }, next: next };
  }

  function texCmd(src, i) {
    var j = i + 1;
    var m = /^[A-Za-z]+/.exec(src.slice(j));
    if (m) return texCommand(m[0], src, j + m[0].length);
    var ch = src.charAt(j);
    if (ch === '\\' || ch === ' ') return { node: { html: ' ' }, next: j + 1 };
    return texCommand(ch, src, j + 1);
  }

  function texDoubleStruck(html) {
    return String(html).replace(/[A-Z]/g, function (c) { return TEX_DOUBLE[c] || c; });
  }

  function texEnvironment(src, next) {
    var g = texBrace(src, next);
    var env = g.text.trim();
    var bodyStart = g.next;
    var spec = '';
    var base = env.replace(/\*$/, '');
    if (base === 'array' || base === 'matrix*') {
      var sp = texBrace(src, bodyStart);
      spec = sp.text;
      bodyStart = sp.next;
    }
    var depth = 1;
    var cursor = bodyStart;
    var endStart = -1;
    while (cursor < src.length) {
      var bi = src.indexOf('\\begin', cursor);
      var ei = src.indexOf('\\end', cursor);
      if (ei < 0) break;
      if (bi >= 0 && bi < ei) { depth += 1; cursor = bi + 6; continue; }
      var e = texBrace(src, ei + 4);
      if (e.text.trim() === env) {
        depth -= 1;
        if (depth === 0) { endStart = ei; break; }
      }
      cursor = ei + 4;
    }
    var body = endStart >= 0 ? src.slice(bodyStart, endStart) : src.slice(bodyStart);
    var nextPos = endStart >= 0 ? texBrace(src, endStart + 4).next : src.length;
    return { node: { html: renderMatrix(base, body, spec) }, next: nextPos };
  }

  function renderMatrix(env, body, spec) {
    var rows = splitTop(body, '\\\\').map(function (r) { return splitTop(r, '&'); });
    var left = '';
    var right = '';
    var cls = 'tx-mat';
    var cellClass = '';
    if (env === 'pmatrix') { left = '('; right = ')'; }
    else if (env === 'bmatrix') { left = '['; right = ']'; }
    else if (env === 'vmatrix') { left = '|'; right = '|'; }
    else if (env === 'Bmatrix') { left = '{'; right = '}'; }
    else if (env === 'Vmatrix') { left = '‖'; right = '‖'; }
    else if (env === 'cases') { left = '{'; cls = 'tx-sys'; cellClass = 'tx-sys'; }
    else if (env === 'aligned' || env === 'align' || env === 'gathered' || env === 'split'
      || env === 'alignat' || env === 'eqnarray') { cls = 'tx-sys'; cellClass = 'tx-sys'; }
    else if (env === 'array') { cls = 'tx-sys'; cellClass = 'tx-sys'; }
    var cols = spec || '';
    var html = rows.map(function (cells) {
      return '<tr>' + cells.map(function (cell, ci) {
        var align = '';
        if (cellClass === 'tx-sys') {
          var specChar = cols.charAt(ci);
          if (specChar === 'r') align = 'text-align:right;';
          else if (specChar === 'c') align = 'text-align:center;';
          else if (!cols && (env === 'aligned' || env === 'align' || env === 'split' || env === 'alignat')) {
            align = ci % 2 === 0 ? 'text-align:right;' : 'text-align:left;';
          } else align = 'text-align:left;';
        }
        var c = (env === 'cases' && ci === 1) ? ' class="tx-sys-l"' : '';
        return '<td' + c + (align ? ' style="' + align + '"' : '') + '>'
          + texAtoms(texSeq(cell, 0).atoms) + '</td>';
      }).join('') + '</tr>';
    }).join('');
    return (left ? '<span class="tx-mat-delim">' + esc(left) + '</span>' : '')
      + '<table class="' + cls + '">' + html + '</table>'
      + (right ? '<span class="tx-mat-delim">' + esc(right) + '</span>' : '');
  }

  /** 把 LaTeX 源码渲染成 HTML（输出中不含裸换行，可直接放进 white-space:pre-wrap 容器）。
   *
   *  KaTeX 优先：页面只要加载了 katex.min.js（编辑器 index.html / 导出的内联脚本都会带上），
   *  公式就整段交给它 —— 编辑器画布、静态 HTML、PDF 打印、PPTX 栅格四路因此完全一致，
   *  不再依赖行高 / 字号 / 缩放等上下文（那是手写实现永远对齐不了的根因）。
   *  取不到 KaTeX 时退回下面那套手写实现，保证页面永远有东西可看。 */
  function tex(src, display) {
    var s = String(src === null || src === undefined ? '' : src).replace(/\s*\n\s*/g, ' ');
    var K = (typeof window !== 'undefined') ? window.katex : null;
    if (K && typeof K.renderToString === 'function') {
      try {
        return K.renderToString(s, {
          displayMode: !!display,
          throwOnError: false,
          errorColor: '#e46a76',
          output: 'html',
        });
      } catch (e) { /* 交给下面的手写实现兜底 */ }
    }
    try {
      var out = texAtoms(texSeq(s, 0).atoms);
      return out || '<span class="tx-sp"></span>';
    } catch (e2) {
      return esc(s);
    }
  }

  ACRender.tex = tex;

  // ---------------------------------------------------------------- 富文本（含公式）
  /* 把 $…$ / $$…$$ 之外的部分原样转义输出；$ 可用 \$ 转义。
   * 行内公式会先过一道启发式判断，避免把「花了 $100 和 $200」当成公式。 */
  function looksLikeMath(body) {
    var s = String(body || '');
    if (!s.trim()) return false;
    if (/[\\^_{}]/.test(s)) return true;
    if (/[=<>±≤≥≠∑∫√∞π∂∇]/.test(s)) return true;
    if (/^[A-Za-z]\s*$/.test(s)) return true;
    return false;
  }

  // ---- 行内富文本（局部加粗 / 斜体 / 下划线 / 文字色 / 高亮）---------------------------
  // props.runs 用「字符区间」描述：{ s, e, b?, i?, u?, c?, bg? }，下标与 props.text 的 JS
  // 字符串下标一一对应。区间越界 / 样式全空的一律丢掉；解析不出就整体退回纯文本渲染。
  // 画布、HTML 导出、PDF、SVG、PPTX 都读同一份 runs：改样式只有这一个入口。
  var RUN_COLOR = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

  function cleanRuns(runs, len) {
    var raw = runs;
    if (typeof raw === 'string') {
      try { raw = JSON.parse(raw); } catch (e) { raw = null; }
    }
    if (!Array.isArray(raw)) return [];
    var out = [];
    for (var k = 0; k < raw.length; k++) {
      var r = raw[k];
      if (!r || typeof r !== 'object') continue;
      var a = Math.max(0, Math.min(len, r.s | 0));
      var b = Math.max(0, Math.min(len, r.e | 0));
      if (!(b > a)) continue;
      var st = {};
      if (r.b) st.b = 1;
      if (r.i) st.i = 1;
      if (r.u) st.u = 1;
      var c = String(r.c || '');
      if (RUN_COLOR.test(c)) st.c = c;
      var g = String(r.bg || '');
      if (RUN_COLOR.test(g)) st.bg = g;
      if (st.b || st.i || st.u || st.c || st.bg) out.push({ s: a, e: b, st: st });
    }
    return out;
  }

  /** 第 i 个字符上叠加出来的行内样式（多个区间重叠时后面的覆盖前面的颜色）。 */
  function runStyleAt(list, i) {
    var st = null;
    for (var k = 0; k < list.length; k++) {
      var r = list[k];
      if (i >= r.s && i < r.e) {
        if (!st) st = {};
        var s = r.st;
        if (s.b) st.b = 1;
        if (s.i) st.i = 1;
        if (s.u) st.u = 1;
        if (s.c) st.c = s.c;
        if (s.bg) st.bg = s.bg;
      }
    }
    return st;
  }

  function runKey(st) {
    if (!st) return '';
    return (st.b ? 'b' : '') + (st.i ? 'i' : '') + (st.u ? 'u' : '')
      + (st.c ? 'c' + st.c : '') + (st.bg ? 'g' + st.bg : '');
  }

  function runCss(st) {
    var css = '';
    if (st.b) css += 'font-weight:700;';
    if (st.i) css += 'font-style:italic;';
    if (st.u) css += 'text-decoration:underline;';
    if (st.c) css += 'color:' + st.c + ';';
    if (st.bg) css += 'background-color:' + st.bg + ';';
    return css;
  }

  /** 一段纯文本按 runs 切分着色；base 是这段文本首字符在原文里的下标。br 为真时 \n → <br/>。 */
  function styleSpan(text, list, base, br) {
    if (!text) return '';
    if (!list.length) return br ? esc(text).replace(/\n/g, '<br/>') : esc(text);
    var out = '';
    var i = 0;
    var n = text.length;
    while (i < n) {
      var st = runStyleAt(list, base + i);
      var key = runKey(st);
      var j = i + 1;
      while (j < n && runKey(runStyleAt(list, base + j)) === key) j++;
      var chunk = esc(text.slice(i, j));
      if (br) chunk = chunk.replace(/\n/g, '<br/>');
      out += st ? '<span style="' + runCss(st) + '">' + chunk + '</span>' : chunk;
      i = j;
    }
    return out;
  }

  /** 只套行内样式、不解析公式的 HTML（量断行与属性面板预览用；\n 原样保留）。 */
  function runsHtml(text, runs, br) {
    var s = String(text === null || text === undefined ? '' : text);
    return styleSpan(s, cleanRuns(runs, s.length), 0, !!br);
  }
  ACRender.runsHtml = runsHtml;
  ACRender.runCss = runCss;
  ACRender.cleanRuns = cleanRuns;

  function richText(text, props) {
    var p = props || {};
    var s = String(text === null || text === undefined ? '' : text);
    var list = cleanRuns(p.runs, s.length);
    if (p.math === false) return styleSpan(s, list, 0, true);
    var out = '';
    var buf = '';
    var base = 0;
    var i = 0;
    var n = s.length;
    function flush() { if (buf) { out += styleSpan(buf, list, base, true); buf = ''; } }
    function math(html, at) {
      var st = runStyleAt(list, at);
      return st ? '<span style="' + runCss(st) + '">' + html + '</span>' : html;
    }
    while (i < n) {
      var ch = s.charAt(i);
      if (ch === '\\' && i + 1 < n && (s.charAt(i + 1) === '$' || s.charAt(i + 1) === '\\')) {
        if (!buf) base = i;
        buf += s.charAt(i + 1);
        i += 2;
        continue;
      }
      if (ch === '$') {
        if (s.charAt(i + 1) === '$') {
          var endB = s.indexOf('$$', i + 2);
          if (endB > -1) {
            var bodyB = s.slice(i + 2, endB);
            if (bodyB.trim()) {
              flush();
              out += math('<span class="tx-block ac-tex">' + tex(bodyB, true) + '</span>', i);
              i = endB + 2;
              continue;
            }
          }
        } else {
          var endI = s.indexOf('$', i + 1);
          if (endI > -1) {
            var bodyI = s.slice(i + 1, endI);
            if (looksLikeMath(bodyI)) {
              flush();
              out += math('<span class="tx-inline ac-tex">' + tex(bodyI, false) + '</span>', i);
              i = endI + 1;
              continue;
            }
          }
        }
        if (!buf) base = i;
        buf += '$';
        i += 1;
        continue;
      }
      if (ch === '\n') {
        flush();
        out += '<br/>';
        i += 1;
        continue;
      }
      if (!buf) base = i;
      buf += ch;
      i += 1;
    }
    flush();
    return out;
  }

  ACRender.richText = richText;

  // ---------------------------------------------------------------- 表格
  // ---------------------------------------------------------------- 表格几何
  /* 列宽 / 行高不再依赖浏览器探针：由 props + 内容按一套确定公式算出来，浏览器与 PPTX
   * 走同一条公式，两端天然一致。宽度单位是「em」——中日韩等全角字符算 1、其余按 latinEm
   * 估，和 Excel 估列宽同思路。常数在 tokens.js 的 geometry.table 里，改一处两端都变。 */

  var CJK_RE = /[\u1100-\u115F\u2E80-\u303E\u3041-\u33FF\u3400-\u4DBF\u4E00-\u9FFF\uA000-\uA4CF\uAC00-\uD7A3\uF900-\uFAFF\uFE30-\uFE4F\uFF00-\uFF60\uFFE0-\uFFE6]/;

  /** 文本宽度（em）：全角 1、半角 latinEm。列宽权重与折行行数都按它估。 */
  function textEm(text) {
    var s = String(text === null || text === undefined ? '' : text);
    var wide = num(tok('geometry', 'table', 'cjkEm'), 1);
    var latin = num(tok('geometry', 'table', 'latinEm'), 0.55);
    var total = 0;
    for (var i = 0; i < s.length; i += 1) total += CJK_RE.test(s[i]) ? wide : latin;
    return total;
  }

  /** 列宽权重：props.columnWidths 优先（缺位列按已给列的均值补），否则按各列内容宽度估。 */
  function tableWeights(props, rows, cols) {
    var p = props || {};
    var given = Array.isArray(p.columnWidths) ? p.columnWidths : null;
    var weights = [];
    var seen = [];
    for (var c = 0; c < cols; c += 1) {
      var v = given && c < given.length ? num(given[c], 0) : 0;
      weights.push(v > 0 ? v : 0);
      if (v > 0) seen.push(v);
    }
    if (seen.length) {
      var avg = seen.reduce(function (a, b) { return a + b; }, 0) / seen.length;
      for (var i = 0; i < cols; i += 1) if (weights[i] <= 0) weights[i] = avg;
      return weights;
    }
    var minEm = num(tok('geometry', 'table', 'minColEm'), 4);
    weights = [];
    for (var c2 = 0; c2 < cols; c2 += 1) {
      var widest = 0;
      for (var r = 0; r < rows.length; r += 1) {
        var cell = Array.isArray(rows[r]) ? rows[r][c2] : '';
        widest = Math.max(widest, textEm(cell));
      }
      weights.push(Math.max(minEm, widest));
    }
    return weights;
  }

  /**
   * 表格几何（两端共用，Python 侧见 export.py 的 _table_geom）：列宽按权重分摊、行高按
   * 「折行数 × 字号 × 行高 + 上下内边距」算，标题另占一行高。
   * opts.w 是表格可用宽度（CSS px），只有导出端算像素列宽时用得上；浏览器侧只需要比例，
   * 所以 tableHtml 直接传 0，列宽用百分比落到 colgroup 上。
   */
  function tableGeom(props, opts) {
    var p = props || {};
    var o = opts || {};
    var rows = Array.isArray(p.rows) ? p.rows : [];
    var cols = 1;
    for (var ri = 0; ri < rows.length; ri += 1) {
      cols = Math.max(cols, Array.isArray(rows[ri]) ? rows[ri].length : 0);
    }
    var density = p.density || 'normal';
    // 密度是内边距的倍率（紧凑 0.5× / 正常 1× / 宽松 2×），两者可叠加。
    // 早先写法是「有 cellPadding 就无视 density」，而 schema 给 cellPadding 写了默认值，
    // 于是每个表格都带 cellPadding，「行高密度」怎么点都没反应——这里改成倍率相乘。
    var cellPad = clamp(num(p.cellPadding, 7), 0, 60);
    var padScale = density === 'compact' ? 0.5 : (density === 'loose' ? 2 : 1);
    var pad = clamp(cellPad * padScale, 0, 60);
    var fs = clamp(num(p.fontSize, 14), 6, 96);
    var headerFs = clamp(num(p.headerFontSize, fs), 6, 96);
    var header = p.header !== false;
    var bw = p.borders === false ? 0 : clamp(num(p.borderWidth, 1), 0, 12);
    var padV = Math.round(pad * 1.05);
    var padH = Math.round(pad * 1.4);
    var lineH = num(tok('geometry', 'table', 'lineHeight'), 1.35);
    var width = Math.max(0, num(o.w, 0));

    var weights = tableWeights(p, rows, cols);
    var total = 0;
    weights.forEach(function (v) { total += v; });
    if (total <= 0) total = 1;
    var ratios = weights.map(function (v) { return v / total; });
    var colW = ratios.map(function (v) { return v * width; });

    var rowH = rows.map(function (row, r) {
      var size = (header && r === 0) ? headerFs : fs;
      var lines = 1;
      for (var c = 0; c < cols; c += 1) {
        var cell = Array.isArray(row) ? row[c] : '';
        if (width <= 0) break;              // 没有像素宽度就无从判断折行，按单行算
        var avail = Math.max(1, colW[c] - 2 * padH - 2 * bw);
        var need = Math.ceil(textEm(cell) / Math.max(0.01, avail / size));
        if (need > lines) lines = need;
      }
      return 2 * padV + lines * size * lineH + 2 * bw;
    });

    return {
      cols: cols, weights: weights, ratios: ratios, colW: colW, rowH: rowH,
      padV: padV, padH: padH, fs: fs, headerFs: headerFs, bw: bw,
      lineHeight: lineH,
    };
  }

  /**
   * 表格实高：把几何公式算出的逐行行高加起来（行高里已含上下内边距与边框）。
   * width 是表格可用宽度（CSS px）；没有宽度时按单行估，只作兜底。
   */
  function tableHeight(props, width) {
    var geom = tableGeom(props, { w: width });
    if (!geom.rowH.length) return 0;
    var total = 0;
    for (var i = 0; i < geom.rowH.length; i += 1) total += geom.rowH[i];
    return Math.ceil(total);
  }

  /**
   * 文本实高（仅浏览器可用）：按给定宽度离屏量一版，供落盘时把框撑到刚好装下。
   * 无 DOM（如 Node 下做语法校验）时返回 0，调用方按「量不到就不动」处理。
   */
  function textHeight(text, style, width) {
    var w = Math.max(0, num(width, 0));
    if (!w || typeof document === 'undefined' || !document.body) return 0;
    var s = style || {};
    var probe = document.createElement('div');
    var css = probe.style;
    css.position = 'absolute';
    css.left = '-100000px';
    css.top = '0';
    css.visibility = 'hidden';
    css.boxSizing = 'border-box';
    css.width = w + 'px';
    css.whiteSpace = 'pre-wrap';
    css.wordBreak = 'break-word';
    if (s.fontFamily) css.fontFamily = String(s.fontFamily);
    if (s.fontSize) css.fontSize = num(s.fontSize, 14) + 'px';
    if (s.fontWeight) css.fontWeight = String(s.fontWeight);
    if (s.fontStyle) css.fontStyle = String(s.fontStyle);
    if (s.letterSpacing) css.letterSpacing = (typeof s.letterSpacing === 'number') ? s.letterSpacing + 'px' : String(s.letterSpacing);
    if (s.textIndent) css.textIndent = (typeof s.textIndent === 'number') ? s.textIndent + 'px' : String(s.textIndent);
    if (s.lineHeight) css.lineHeight = String(s.lineHeight);
    probe.textContent = (text === null || text === undefined) ? '' : String(text);
    document.body.appendChild(probe);
    var h = probe.offsetHeight;
    document.body.removeChild(probe);
    return Math.ceil(h);
  }

  ACRender.textEm = textEm;
  ACRender.tableGeom = tableGeom;
  ACRender.tableHeight = tableHeight;
  ACRender.textHeight = textHeight;

  /**
   * 表格渲染：支持列宽、逐列对齐、表头配色、边框色、斑马纹、单元格 / 整行底色、
   * 密度、圆角投影与合并单元格（merges）。
   * merges 写法：[[起始行, 起始列, 跨行数, 跨列数], …]，行 \ 列都从 0 起算。
   */
  function tableHtml(props) {
    var p = props || {};
    var rows = Array.isArray(p.rows) ? p.rows : [];
    if (!rows.length) return '<div class="ac-table-empty">暂无数据</div>';
    var header = p.header !== false;
    var colCount = 1;
    for (var ri = 0; ri < rows.length; ri += 1) {
      var rl = Array.isArray(rows[ri]) ? rows[ri].length : 0;
      if (rl > colCount) colCount = rl;
    }
    var geom = tableGeom(p, {});
    var padV = geom.padV;
    var padH = geom.padH;
    var fs = geom.fs;
    var headerFs = geom.headerFs;
    var bw = geom.bw;
    var borderColor = safeColor(p.borderColor, '#d0d5dd');
    var headerBg = safeColor(p.headerBg, '#f2f4f7');
    var headerColor = safeColor(p.headerColor, '#344054');
    var altBg = safeColor(p.altBg, '#f7f9fc');
    var rowBg = safeColor(p.rowBg, '');
    var hlDefault = safeColor(p.highlightColor, '#fff3cd');
    var aligns = Array.isArray(p.aligns) ? p.aligns : null;
    var defaultAlign = p.align || 'left';
    var headerAlign = p.headerAlign || (aligns && aligns[0]) || defaultAlign;
    var headerBold = p.headerBold !== false;
    var firstColBold = !!p.firstColBold;
    var valign = p.verticalAlign || 'middle';
    var zebra = !!p.zebra;

    // ---- 合并单元格：算好跳过表和跨行列数
    var skip = {};
    var span = {};
    mergesOf(p.merges).forEach(function (m) {
      var r = Math.round(num(m[0], 0));
      var c = Math.round(num(m[1], 0));
      var rs = clamp(Math.round(num(m[2], 1)), 1, 200);
      var cs = clamp(Math.round(num(m[3], 1)), 1, 200);
      if (r < 0 || c < 0) return;
      span[r + ',' + c] = [rs, cs];
      for (var a = r; a < r + rs; a += 1) {
        for (var b = c; b < c + cs; b += 1) {
          if (a === r && b === c) continue;
          skip[a + ',' + b] = true;
        }
      }
    });

    // ---- 高亮：整行 / 单格
    var hlRow = {};
    var hlCell = {};
    (Array.isArray(p.highlights) ? p.highlights : []).forEach(function (h) {
      if (!Array.isArray(h) || h.length < 2) return;
      var r = Math.round(num(h[0], -1));
      if (r < 0) return;
      var color = safeColor(h[2], '') || hlDefault;
      var col = h[1];
      if (col === -1 || col === null || col === undefined || col === '' || col === '*') hlRow[r] = color;
      else hlCell[r + ',' + Math.round(num(col, 0))] = color;
    });

    // ---- 列宽：按 IR 权重分摊（见 tableGeom），与 PPTX 侧同一条公式
    var cg = '';
    for (var cc = 0; cc < colCount; cc += 1) {
      cg += '<col style="width:' + (geom.ratios[cc] * 100).toFixed(4) + '%">';
    }
    var colgroup = '<colgroup>' + cg + '</colgroup>';

    var body = '';
    for (var r = 0; r < rows.length; r += 1) {
      var row = Array.isArray(rows[r]) ? rows[r] : [];
      var isHead = header && r === 0;
      var bodyIndex = header ? r - 1 : r;
      var bg = '';
      if (!isHead) {
        // 斑马纹优先于行底色：schema 给 rowBg 写了默认值，若让 rowBg 先行，
        // 每个表格都会被整块铺色，斑马纹（与条纹色）永远看不到。
        if (hlRow[r]) bg = hlRow[r];
        else if (zebra) bg = bodyIndex % 2 === 1 ? altBg : rowBg;
        else if (rowBg) bg = rowBg;
      }
      var tds = '';
      for (var ci = 0; ci < colCount; ci += 1) {
        if (skip[r + ',' + ci]) continue;
        var cellSpan = span[r + ',' + ci];
        var cellBg = hlCell[r + ',' + ci] || bg;
        var style = [
          'padding:' + padV + 'px ' + padH + 'px',
          'font-size:' + (isHead ? headerFs : fs) + 'px',
          'line-height:' + geom.lineHeight,
          'text-align:' + (isHead ? headerAlign : (aligns ? (aligns[ci] || defaultAlign) : defaultAlign)),
          'vertical-align:' + valign,
          bw > 0 ? 'border:' + bw + 'px solid ' + borderColor : 'border:none',
        ];
        if (isHead) {
          if (headerBg) style.push('background:' + headerBg);
          if (headerColor) style.push('color:' + headerColor);
          // 显式写非粗字重：否则 headerBold=false 时什么都不写，浏览器 UA 的 th{font-weight:bold} 会顶上来
          style.push('font-weight:' + (headerBold ? 700 : 400));
        } else {
          if (cellBg) style.push('background:' + cellBg);
          if (firstColBold && ci === 0) style.push('font-weight:600');
        }
        var attrs = ' data-ac-r="' + r + '" data-ac-c="' + ci + '"';
        if (cellSpan) {
          if (cellSpan[0] > 1) attrs += ' rowspan="' + cellSpan[0] + '"';
          if (cellSpan[1] > 1) attrs += ' colspan="' + cellSpan[1] + '"';
        }
        var tag = isHead ? 'th' : 'td';
        tds += '<' + tag + attrs + ' style="' + style.join(';') + '">'
          + esc(row[ci]) + '</' + tag + '>';
      }
      body += '<tr>' + tds + '</tr>';
    }

    var wrapStyle = [];
    var radius = clamp(num(p.radius, 0), 0, 40);
    if (radius) wrapStyle.push('border-radius:' + radius + 'px');
    if (p.shadow) wrapStyle.push('box-shadow:' + shadowCss(tok('shadow', 'table')));
    if (p.fontFamily) wrapStyle.push('font-family:' + p.fontFamily);
    var tableStyle = 'font-size:' + fs + 'px;'
      + 'height:100%;'             // 撑满元素框，行按比例摊高，「垂直对齐」才有可见效果
      + 'table-layout:fixed;'      // 列宽由 colgroup 的百分比定，两端才可能一致
      + (bw > 0 ? '' : 'border-collapse:collapse;');
    return '<div class="ac-table-wrap" style="' + wrapStyle.join(';') + '">'
      + '<table class="ac-table" style="' + tableStyle + '">' + colgroup + body + '</table></div>';
  }

  function mergesOf(value) {
    if (!Array.isArray(value)) return [];
    return value.filter(function (m) { return Array.isArray(m) && m.length >= 2; });
  }

  ACRender.tableHtml = tableHtml;

  // ---------------------------------------------------------------- 统计图
  var CHART_PALETTE = ['#2f6fed', '#f2a33c', '#34b98a', '#e46a76', '#8a7cf0',
    '#3fb6d3', '#b57ce0', '#f0755f', '#5aa469', '#d9a441'];

  var CHART_KIND_ALIAS = {
    column: 'bar', columns: 'bar', barchart: 'bar', vbar: 'bar',
    hbar: 'hbar', horizontalbar: 'hbar', barh: 'hbar', rowbar: 'hbar',
    groupedbar: 'bar', stackedbar: 'bar', hgroupedbar: 'hbar', hstackedbar: 'hbar',
    linechart: 'line', spline: 'line', curve: 'line',
    areachart: 'area', stackedarea: 'stackedArea',
    circle: 'pie', piechart: 'pie', ring: 'donut', doughnut: 'donut', donutchart: 'donut',
    rosechart: 'rose', nightingale: 'rose', polararea: 'rose',
    radarchart: 'radar', spider: 'radar', web: 'radar',
    scatterplot: 'scatter', point: 'scatter', xy: 'scatter',
    bubbles: 'bubble', bubblechart: 'bubble',
    funnelchart: 'funnel', gaugechart: 'gauge', dial: 'gauge', speedometer: 'gauge',
    progressbar: 'progress', bars: 'progress', ranking: 'progress',
    // 论文级统计图形
    box: 'box', boxchart: 'box', boxplot: 'box', boxwhisker: 'box', boxandwhisker: 'box',
    violin: 'violin', violinplot: 'violin', violinchart: 'violin',
    hist: 'hist', histchart: 'hist', histogram: 'hist',
    ecdf: 'ecdf', cdf: 'ecdf', cumulative: 'ecdf', cumulativecurve: 'ecdf',
    heatmap: 'heatmap', heat: 'heatmap', matrix: 'heatmap',
    errorbar: 'errorbar', errorbars: 'errorbar', meanbar: 'errorbar',
  };

  // 配色预设：论文里常用「色盲友好」和「期刊低饱和」两套，另有灰阶给黑白印刷
  var CHART_PALETTE_PRESETS = {
    okabe: ['#0072b2', '#e69f00', '#009e73', '#d55e00', '#cc79a7', '#56b4e9', '#f0e442', '#999999'],
    nature: ['#3c5488', '#e64b35', '#00a087', '#4dbbd5', '#f39b7f', '#8491b4', '#91d1c2', '#b09c85'],
    grey: ['#404040', '#7d7d7d', '#a8a8a8', '#c9c9c9', '#5c5c5c', '#919191', '#bdbdbd', '#e0e0e0'],
  };

  // 热力图色阶：由低到高的取样点，中间线性插值
  var CHART_HEAT_SCALES = {
    viridis: ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725'],
    blue: ['#f7fbff', '#c6dbef', '#6baed6', '#2171b5', '#08306b'],
    red: ['#fff5f0', '#fcbba1', '#fb6a4a', '#cb181d', '#67000d'],
    green: ['#f7fcf5', '#c7e9c0', '#74c476', '#238b45', '#00441b'],
    grey: ['#ffffff', '#d9d9d9', '#969696', '#525252', '#000000'],
    diverging: ['#2166ac', '#67a9cf', '#f7f7f7', '#ef8a62', '#b2182b'],
  };

  // ---- 统计图形（箱线 / 小提琴 / 直方 / 累积 / 误差棒 / 热力图）的样本规约

  /** 单元格是不是一个数（空串 / 布尔 / 乱码都不算）。 */
  function isNumCell(c) {
    if (c === null || c === undefined || typeof c === 'boolean') return false;
    if (typeof c === 'number') return isFinite(c);
    return String(c).trim() !== '' && isFinite(Number(c));
  }

  /**
   * 分组取样：第一列是分组名（同名合并成一组），该行其余数值单元格都算这组的样本。
   * 于是「长表」[["A",3.1],["A",3.5],["B",4.2]] 与「宽表」[["A",1,2,3],["B",4,5,6]] 读法一致。
   */
  function statGroups(p) {
    var rows = (p.rows || []).filter(function (r) { return Array.isArray(r) && r.length; });
    var buf = {};
    var out = [];
    var defName = String(p.seriesName || '样本');
    rows.forEach(function (r) {
      var name = '';
      var vals = [];
      r.forEach(function (c, ci) {
        if (ci === 0 && !isNumCell(c)) { name = String(c === null || c === undefined ? '' : c).trim(); return; }
        if (isNumCell(c)) vals.push(Number(c));
      });
      if (!vals.length) return;
      var key = name || defName;
      if (!buf[key]) { buf[key] = { name: key, values: [], rows: 0 }; out.push(buf[key]); }
      buf[key].rows += 1;
      buf[key].values = buf[key].values.concat(vals);
    });
    return out;
  }

  /** 误差棒数据：第一列组名（可省），第一个数值是柱高 / 均值，第二个是误差（±）。 */
  function errorRows(p) {
    var rows = (p.rows || []).filter(function (r) { return Array.isArray(r) && r.length; });
    var out = [];
    rows.forEach(function (r, ri) {
      var name = '';
      var nums = [];
      r.forEach(function (c, ci) {
        if (ci === 0 && !isNumCell(c)) { name = String(c === null || c === undefined ? '' : c).trim(); return; }
        if (isNumCell(c)) nums.push(Number(c));
      });
      if (!nums.length) return;
      out.push({ name: name || ('第' + (ri + 1) + '组'), mean: nums[0], err: nums.length > 1 ? Math.abs(nums[1]) : 0 });
    });
    return out;
  }

  function quantile(sorted, q) {
    var n = sorted.length;
    if (!n) return 0;
    if (n === 1) return sorted[0];
    var pos = (n - 1) * q;
    var lo = Math.floor(pos);
    var hi = Math.ceil(pos);
    if (lo === hi) return sorted[lo];
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }

  /** 箱线五数概括：Q1 / 中位数 / Q3 / 须（1.5×IQR 内最远观测）/ 离群点 / 均值。 */
  function boxStats(values) {
    var s = values.slice().sort(function (a, b) { return a - b; });
    var n = s.length;
    if (!n) return null;
    var q1 = quantile(s, 0.25);
    var med = quantile(s, 0.5);
    var q3 = quantile(s, 0.75);
    var iqr = q3 - q1;
    var loF = q1 - 1.5 * iqr;
    var hiF = q3 + 1.5 * iqr;
    var inside = s.filter(function (v) { return v >= loF && v <= hiF; });
    var sum = 0;
    for (var i = 0; i < n; i += 1) sum += s[i];
    return {
      q1: q1, med: med, q3: q3, iqr: iqr,
      lo: inside.length ? inside[0] : s[0],
      hi: inside.length ? inside[inside.length - 1] : s[n - 1],
      outliers: s.filter(function (v) { return v < loF || v > hiF; }),
      mean: sum / n, n: n,
    };
  }

  /** 高斯核密度（Silverman 带宽）：在 [lo,hi] 上等分取样，返回 [[值, 密度], ...]。 */
  function kdeCurve(values, lo, hi, steps) {
    var n = values.length;
    if (!n) return [];
    var mean = 0;
    var i;
    for (i = 0; i < n; i += 1) mean += values[i];
    mean /= n;
    var varsum = 0;
    for (i = 0; i < n; i += 1) varsum += (values[i] - mean) * (values[i] - mean);
    var sd = Math.sqrt(varsum / Math.max(1, n - 1)) || 0;
    var bw = 1.06 * sd * Math.pow(n, -0.2);
    if (!(bw > 0)) bw = Math.max(Math.abs(hi - lo) / 40, 1e-6);
    var k = 1 / (n * bw * Math.sqrt(2 * Math.PI));
    var pts = [];
    for (var t = 0; t <= steps; t += 1) {
      var x = lo + (hi - lo) * t / steps;
      var acc = 0;
      for (var j = 0; j < n; j += 1) {
        var u = (x - values[j]) / bw;
        acc += Math.exp(-0.5 * u * u);
      }
      pts.push([x, acc * k]);
    }
    return pts;
  }

  // ---- 统计层：由重复样本算 SD / SEM / 95%CI、Welch t 检验、回归拟合

  /** 双侧 95% t 临界值（df 1..30 查表，更大自由度用正态近似）。 */
  var T95_TABLE = [0, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262,
    2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093,
    2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042];
  function tCrit95(df) {
    var k = Math.max(1, Math.round(df));
    if (k < T95_TABLE.length) return T95_TABLE[k];
    return 1.96 + 2.4 / k;
  }

  /** 样本统计：n / 均值 / 样本标准差 / 标准误 / 95%CI 半宽。 */
  function sampleStats(values) {
    var v = (values || []).filter(function (x) { return isFinite(x); });
    var n = v.length;
    if (!n) return { n: 0, mean: 0, sd: 0, sem: 0, ci: 0 };
    var sum = 0;
    var i;
    for (i = 0; i < n; i += 1) sum += v[i];
    var mean = sum / n;
    var ss = 0;
    for (i = 0; i < n; i += 1) { var dv = v[i] - mean; ss += dv * dv; }
    var sd = n > 1 ? Math.sqrt(ss / (n - 1)) : 0;
    var sem = sd / Math.sqrt(n);
    return { n: n, mean: mean, sd: sd, sem: sem, ci: tCrit95(n - 1) * sem };
  }

  /** 按误差类型取误差半宽：sd / sem / ci95。 */
  function errHalf(st, type) {
    if (!st || !(st.n > 0)) return 0;
    if (type === 'sd') return st.sd;
    if (type === 'sem') return st.sem;
    if (type === 'ci95') return st.ci;
    return 0;
  }

  /** Lanczos 近似的 ln Γ(x)。 */
  function logGamma(x) {
    var cof = [76.18009172947146, -86.50532032941677, 24.01409824083091,
      -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5];
    var y = x;
    var tmp = x + 5.5;
    tmp -= (x + 0.5) * Math.log(tmp);
    var ser = 1.000000000190015;
    for (var j = 0; j < 6; j += 1) { y += 1; ser += cof[j] / y; }
    return -tmp + Math.log(2.5066282746310005 * ser / x);
  }

  /** 连分式展开（Numerical Recipes），供 betai 调用。 */
  function betacf(a, b, x) {
    var MAXIT = 220;
    var EPS = 3e-12;
    var FPMIN = 1e-300;
    var qab = a + b;
    var qap = a + 1;
    var qam = a - 1;
    var c = 1;
    var dd = 1 - qab * x / qap;
    if (Math.abs(dd) < FPMIN) dd = FPMIN;
    dd = 1 / dd;
    var h = dd;
    for (var m = 1; m <= MAXIT; m += 1) {
      var m2 = 2 * m;
      var aa = m * (b - m) * x / ((qam + m2) * (a + m2));
      dd = 1 + aa * dd;
      if (Math.abs(dd) < FPMIN) dd = FPMIN;
      c = 1 + aa / c;
      if (Math.abs(c) < FPMIN) c = FPMIN;
      dd = 1 / dd;
      h *= dd * c;
      aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2));
      dd = 1 + aa * dd;
      if (Math.abs(dd) < FPMIN) dd = FPMIN;
      c = 1 + aa / c;
      if (Math.abs(c) < FPMIN) c = FPMIN;
      dd = 1 / dd;
      var del = dd * c;
      h *= del;
      if (Math.abs(del - 1) < EPS) break;
    }
    return h;
  }

  /** 正则化不完全贝塔 I_x(a,b)。 */
  function betai(a, b, x) {
    if (!(x > 0)) return 0;
    if (x >= 1) return 1;
    var bt = Math.exp(logGamma(a + b) - logGamma(a) - logGamma(b)
      + a * Math.log(x) + b * Math.log(1 - x));
    if (x < (a + 1) / (a + b + 2)) return bt * betacf(a, b, x) / a;
    return 1 - bt * betacf(b, a, 1 - x) / b;
  }

  /** Student t 双侧 p 值。 */
  function tTwoTailP(t, df) {
    if (!isFinite(t)) return 1;
    if (!(df > 0)) return 1;
    var x = df / (df + t * t);
    var p = betai(df / 2, 0.5, x);
    return clamp(p, 0, 1);
  }

  /** Welch t 检验（不假设方差齐性，含 Satterthwaite 自由度）。样本不足返回 null。 */
  function welchT(a, b) {
    var sa = sampleStats(a);
    var sb = sampleStats(b);
    if (sa.n < 2 || sb.n < 2) return null;
    var va = sa.sd * sa.sd / sa.n;
    var vb = sb.sd * sb.sd / sb.n;
    var denom = va + vb;
    if (!(denom > 0)) return null;
    var t = (sa.mean - sb.mean) / Math.sqrt(denom);
    var df = (denom * denom) / ((va * va) / (sa.n - 1) + (vb * vb) / (sb.n - 1));
    return { t: t, df: df, p: tTwoTailP(t, df), a: sa, b: sb };
  }

  /** p 值 → 显著性星号（无可靠样本标 n.d.）。 */
  function sigStars(p) {
    if (!isFinite(p)) return 'n.d.';
    if (p < 0.0001) return '****';
    if (p < 0.001) return '***';
    if (p < 0.01) return '**';
    if (p < 0.05) return '*';
    return 'n.s.';
  }

  /** Holm–Bonferroni 校正（返回与输入同序的校正后 p 值，单调不减并封顶 1）。 */
  function holmAdjust(ps) {
    var m = ps.length;
    var order = ps.map(function (p, i) { return [p, i]; })
      .sort(function (x, y) { return x[0] - y[0]; });
    var adj = new Array(m);
    var running = 0;
    for (var k = 0; k < m; k += 1) {
      var val = (m - k) * order[k][0];
      if (!(val < 1)) val = 1;
      if (val < running) val = running;
      running = val;
      adj[order[k][1]] = val;
    }
    return adj;
  }

  /** 高斯消元解 A·x = b（A 为 n×n），奇异返回 null。 */
  function solveLinear(A, b) {
    var n = b.length;
    var M = A.map(function (row, i) { return row.slice().concat([b[i]]); });
    for (var col = 0; col < n; col += 1) {
      var piv = col;
      for (var r = col + 1; r < n; r += 1) {
        if (Math.abs(M[r][col]) > Math.abs(M[piv][col])) piv = r;
      }
      if (Math.abs(M[piv][col]) < 1e-12) return null;
      var tmp = M[col]; M[col] = M[piv]; M[piv] = tmp;
      for (var r2 = col + 1; r2 < n; r2 += 1) {
        var f = M[r2][col] / M[col][col];
        for (var c2 = col; c2 <= n; c2 += 1) M[r2][c2] -= f * M[col][c2];
      }
    }
    var x = new Array(n);
    for (var i2 = n - 1; i2 >= 0; i2 -= 1) {
      var sum = M[i2][n];
      for (var j2 = i2 + 1; j2 < n; j2 += 1) sum -= M[i2][j2] * x[j2];
      x[i2] = sum / M[i2][i2];
    }
    return x;
  }

  /** 最小二乘多项式拟合，返回系数（升幂，c[0] 为常数项）；点数不足或奇异返回 null。 */
  function polyFit(xs, ys, degree) {
    var n = xs.length;
    if (n < degree + 1) return null;
    var m = degree + 1;
    var A = [];
    var b = [];
    var i;
    for (i = 0; i < m; i += 1) { A.push(new Array(m).fill(0)); b.push(0); }
    for (var k = 0; k < n; k += 1) {
      for (i = 0; i < m; i += 1) {
        for (var j = 0; j < m; j += 1) A[i][j] += Math.pow(xs[k], i + j);
        b[i] += Math.pow(xs[k], i) * ys[k];
      }
    }
    return solveLinear(A, b);
  }

  /** 指数拟合 y = a·e^(b·x)（对 ln y 做线性回归）；含非正 y 或无解返回 null。 */
  function expFit(xs, ys) {
    var n = xs.length;
    if (n < 2) return null;
    var ly = [];
    for (var i = 0; i < n; i += 1) {
      if (!(ys[i] > 0)) return null;
      ly.push(Math.log(ys[i]));
    }
    var sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (var k = 0; k < n; k += 1) {
      sx += xs[k]; sy += ly[k];
      sxx += xs[k] * xs[k]; sxy += xs[k] * ly[k];
    }
    var denom = n * sxx - sx * sx;
    if (!(Math.abs(denom) > 1e-12)) return null;
    var b = (n * sxy - sx * sy) / denom;
    return { a: Math.exp((sy - b * sx) / n), b: b };
  }

  /** 决定系数 R²。 */
  function rSquared(xs, ys, fn) {
    var n = ys.length;
    if (!n) return 0;
    var mean = 0;
    var i;
    for (i = 0; i < n; i += 1) mean += ys[i];
    mean /= n;
    var ssTot = 0;
    var ssRes = 0;
    for (i = 0; i < n; i += 1) {
      var pred = fn(xs[i]);
      ssTot += (ys[i] - mean) * (ys[i] - mean);
      ssRes += (ys[i] - pred) * (ys[i] - pred);
    }
    if (!(ssTot > 0)) return ssRes > 0 ? 0 : 1;
    return 1 - ssRes / ssTot;
  }

  /** 系数文本（去掉多余的尾零）。 */
  function fmtCoef(v, digits) {
    var s = (Number(v) || 0).toFixed(digits === undefined ? 3 : digits);
    s = s.replace(/\.?0+$/, '');
    if (s === '' || s === '-' || s === '-0') s = '0';
    return s;
  }

  /** 多项式方程文本（升幂系数 → y = a + b·x + c·x²）。 */
  function polyEqText(c) {
    var sup = ['', '', '²', '³', '⁴', '⁵', '⁶'];
    var out = '';
    for (var i = c.length - 1; i >= 0; i -= 1) {
      if (Math.abs(c[i]) < 1e-12) continue;
      var mag = fmtCoef(Math.abs(c[i]), 3);
      var term;
      if (i === 0) term = mag;
      else if (i === 1) term = (mag === '1' ? '' : mag + '·') + 'x';
      else term = (mag === '1' ? '' : mag + '·') + 'x' + (sup[i] || ('^' + i));
      if (!out) out = (c[i] < 0 ? '-' : '') + term;
      else out += (c[i] < 0 ? ' − ' : ' + ') + term;
    }
    return 'y = ' + (out || '0');
  }

  /** 回归拟合入口：返回 {fn, eq, r2}；类型不支持 / 数据不足返回 null。 */
  function fitSummary(xs, ys, type) {
    if (!type || type === 'none' || xs.length < 2) return null;
    var fn = null;
    var eq = '';
    if (type === 'linear' || type === 'quad' || type === 'cubic') {
      var coeffs = polyFit(xs, ys, type === 'linear' ? 1 : (type === 'quad' ? 2 : 3));
      if (!coeffs) return null;
      fn = function (x) {
        var s = 0;
        for (var i = 0; i < coeffs.length; i += 1) s += coeffs[i] * Math.pow(x, i);
        return s;
      };
      eq = polyEqText(coeffs);
    } else if (type === 'exp') {
      var ex = expFit(xs, ys);
      if (!ex) return null;
      fn = function (x) { return ex.a * Math.exp(ex.b * x); };
      eq = 'y = ' + fmtCoef(ex.a, 3) + '·e^(' + fmtCoef(ex.b, 3) + 'x)';
    } else {
      return null;
    }
    return { fn: fn, eq: eq, r2: rSquared(xs, ys, fn), type: type };
  }

  /**
   * 解析「对比」字段：逗号分隔的若干对，「A-B」自动检验，
   * 「A-B:0.008」手动给 p 值，「A-B:***」手动给星号。
   */
  function parseCompare(text) {
    if (!text) return [];
    var out = [];
    String(text).split(/[,，;；\n]/).forEach(function (seg) {
      var s = String(seg).trim();
      if (!s) return;
      var val = null;
      var mc = s.match(/^(.*?)\s*[:：]\s*(.*)$/);
      if (mc) { s = mc[1].trim(); val = mc[2].trim() || null; }
      var mp = s.match(/^(.*?)\s*[-–—]\s*(.*)$/);
      if (!mp) return;
      var a = mp[1].trim();
      var b = mp[2].trim();
      if (!a || !b) return;
      var item = { a: a, b: b, p: null, stars: null };
      if (val) {
        if (/^[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?$/.test(val)) item.p = Number(val);
        else item.stars = val;
      }
      out.push(item);
    });
    return out;
  }

  function hexToRgb(hex) {
    var s = String(hex === null || hex === undefined ? '' : hex).trim().replace('#', '');
    if (s.length === 3) s = s[0] + s[0] + s[1] + s[1] + s[2] + s[2];
    if (s.length !== 6) return null;
    var n = parseInt(s, 16);
    if (isNaN(n)) return null;
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  /** 在色阶上取 t∈[0,1] 处的颜色（线性插值，可服务热力图与渐变色条）。 */
  function mixColors(list, t) {
    var cs = list && list.length ? list : ['#888888'];
    if (cs.length === 1) return cs[0];
    var x = clamp(t, 0, 1) * (cs.length - 1);
    var i = Math.min(cs.length - 2, Math.floor(x));
    var f = x - i;
    var a = hexToRgb(cs[i]);
    var b = hexToRgb(cs[i + 1]);
    if (!a || !b) return cs[i];
    var out = [];
    for (var k = 0; k < 3; k += 1) out.push(('0' + Math.round(a[k] + (b[k] - a[k]) * f).toString(16)).slice(-2));
    return '#' + out.join('');
  }

  /** 把 [lo,hi] 扩成「刻度间隔好看」的区间（统计图形的纵轴从这里取端点）。 */
  function niceRange(lo, hi, count) {
    var span = hi - lo;
    if (!(span > 0)) {
      span = Math.abs(hi) || 1;
      lo = (hi || 0) - span / 2;
      hi = lo + span;
    }
    var raw = span / Math.max(1, count);
    var exp = Math.floor(Math.log(raw) / Math.LN10);
    var base = Math.pow(10, exp);
    var f = raw / base;
    var step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * base;
    var lo2 = Math.floor(lo / step) * step;
    var hi2 = Math.ceil(hi / step) * step;
    return { lo: lo2, hi: hi2, step: step, count: Math.max(1, Math.round((hi2 - lo2) / step)) };
  }

  function normKind(kind) {
    var k = String(kind || 'bar').trim();
    var lower = k.toLowerCase().replace(/[\s_-]/g, '');
    if (CHART_KIND_ALIAS[lower]) return CHART_KIND_ALIAS[lower];
    if (k === 'stackedArea') return 'stackedArea';
    return k;
  }

  function chartColors(p) {
    // palette 允许写成数组，也允许写成逗号分隔的字符串（AI 常这么给），两种都得认
    var preset = CHART_PALETTE_PRESETS[String(p.palettePreset || '')];
    if (preset) return preset;   // 选了预设就覆盖自定义配色，语义明确、不用猜谁优先
    var raw = p.palette;
    if (typeof raw === 'string') raw = raw.split(/[,，\n]/);
    var list = Array.isArray(raw)
      ? raw.map(function (c) { return String(c == null ? '' : c).trim(); }).filter(Boolean)
      : [];
    return list.length ? list : CHART_PALETTE;
  }

  /** 取调色板颜色：支持「逐类配色」和「逐系列配色」两种取法。 */
  function pickColor(colors, i) {
    return colors[((i % colors.length) + colors.length) % colors.length];
  }

  /** 单元格是否真的是数值（空串不算，避免 Number('') === 0 被当成数值）。 */
  function isNumericCell(v) {
    if (typeof v === 'number') return isFinite(v);
    if (typeof v === 'string') {
      var s = v.trim();
      return s !== '' && isFinite(Number(s));
    }
    return false;
  }

  /** 散点 / 气泡的数据整形：x 必须是数值列，气泡半径取尺寸列。
   *  表格里两种常见写法都认：
   *    [x, y(, size)]          首列就是数值 x
   *    [分组, x, y(, size)]    首列是文字分组，x 顺延到第 2 列
   *  表头行 / 空行（x 或 y 不是数值）直接丢掉，不参与绘图。 */
  function xyData(p, rows, kind) {
    var maxCols = 0;
    rows.forEach(function (r) { if (r.length > maxCols) maxCols = r.length; });
    var col0Num = 0;
    var col1Num = 0;
    rows.forEach(function (r) {
      if (isNumericCell(r[0])) col0Num += 1;
      if (isNumericCell(r[1])) col1Num += 1;
    });
    var labelCol = col0Num === 0 && col1Num > 0;   // 首列全是文字 → 当分组列丢掉
    var xCol = labelCol ? 1 : 0;
    var yCol = xCol + 1;
    if (maxCols <= yCol) return null;              // 列数不够，交回常规读法
    var sizeCol = kind === 'bubble' && maxCols > yCol + 1 ? yCol + 1 : -1;
    var kept = rows.filter(function (r) {
      return isNumericCell(r[xCol]) && isNumericCell(r[yCol]);
    });
    if (!kept.length) return null;
    var headers = Array.isArray(p.headers) ? p.headers : null;
    var yCols = [];
    for (var c = yCol; c < maxCols; c += 1) { if (c !== sizeCol) yCols.push(c); }
    if (!yCols.length) yCols = [yCol];
    var names = yCols.map(function (ci) {
      return (headers && headers[ci]) || (yCols.length > 1 ? ('系列' + ci) : (p.seriesName || '数值'));
    });
    if (typeof p.seriesNames === 'string' && p.seriesNames.trim()) {
      var custom = p.seriesNames.split(/[,，]/).map(function (s) { return s.trim(); });
      for (var i = 0; i < names.length && i < custom.length; i += 1) {
        if (custom[i]) names[i] = custom[i];
      }
    }
    return {
      rows: kept,
      labels: kept.map(function (r) {
        return labelCol ? String(r[0] === null || r[0] === undefined ? '' : r[0]) : String(num(r[xCol], 0));
      }),
      names: names,
      values: yCols.map(function (ci) { return kept.map(function (r) { return num(r[ci], 0); }); }),
      colCount: maxCols,
      xCol: xCol,
      sizeCol: sizeCol,
      xVals: kept.map(function (r) { return num(r[xCol], 0); }),
      sizeVals: sizeCol >= 0 ? kept.map(function (r) { return num(r[sizeCol], 0); }) : null,
    };
  }

  /** 数据模型：首列是类目，其余列各自成为一个系列；散点 / 气泡按数值 x 读表。 */
  function chartData(p, kind) {
    var rows = (p.rows || []).filter(function (r) { return Array.isArray(r) && r.length; });
    if (kind === 'scatter' || kind === 'bubble') {
      var xy = xyData(p, rows, kind);
      if (xy) return xy;
    }
    var headers = Array.isArray(p.headers) ? p.headers : null;
    var labels = rows.map(function (r) {
      var v = r[0];
      return v === null || v === undefined ? '' : String(v);
    });
    var maxCols = 0;
    rows.forEach(function (r) { if (r.length > maxCols) maxCols = r.length; });
    var names = [];
    var values = [];
    if (maxCols >= 3) {
      for (var c = 1; c < maxCols; c += 1) {
        names.push((headers && headers[c]) || ('系列' + c));
        values.push(rows.map(function (r) { return num(r[c], 0); }));
      }
    } else {
      names.push((headers && headers[1]) || p.seriesName || '数值');
      values.push(rows.map(function (r) { return num(r[1], 0); }));
    }
    if (typeof p.seriesNames === 'string' && p.seriesNames.trim()) {
      var custom = p.seriesNames.split(/[,，]/).map(function (s) { return s.trim(); });
      for (var i = 0; i < names.length && i < custom.length; i += 1) {
        if (custom[i]) names[i] = custom[i];
      }
    }
    return { rows: rows, labels: labels, names: names, values: values, colCount: maxCols };
  }

  /** 轴上限取「好看的整数」，避免刻度出现 3333.33 这种值。 */
  function niceMax(v) {
    var x = Math.abs(v);
    if (x <= 0) return 1;
    var exp = Math.floor(Math.log(x) / Math.LN10);
    var base = Math.pow(10, exp);
    var f = x / base;
    var nice = f <= 1 ? 1 : (f <= 2 ? 2 : (f <= 2.5 ? 2.5 : (f <= 5 ? 5 : 10)));
    return nice * base;
  }

  function truncLabel(s, max) {
    var t = String(s === null || s === undefined ? '' : s);
    return t.length > max ? t.slice(0, Math.max(1, max - 1)) + '…' : t;
  }

  // 估算文本宽度：中文/全角按 1em，西文数字按 0.56em（够用即可，不做精确排版）
  function estTextWidth(s, fs) {
    var t = String(s === null || s === undefined ? '' : s);
    var w = 0;
    for (var i = 0; i < t.length; i += 1) {
      var c = t.charCodeAt(i);
      var wide = (c >= 0x1100 && c <= 0x115f) || (c >= 0x2e80 && c <= 0xa4cf)
        || (c >= 0xac00 && c <= 0xd7a3) || (c >= 0xf900 && c <= 0xfaff)
        || (c >= 0xfe30 && c <= 0xfe6f) || (c >= 0xff00 && c <= 0xff60);
      w += (wide ? 1 : 0.6) * fs;
    }
    return w;
  }

  // 在 maxW 内尽量用大字号；字号压到 8 还放不下就截断加省略号
  function fitLabel(s, maxW, fs, minChars) {
    var t = String(s === null || s === undefined ? '' : s);
    var f = fs;
    while (f > 8 && estTextWidth(t, f) > maxW) f -= 1;
    if (estTextWidth(t, f) <= maxW) return { text: t, fs: f };
    var n = t.length;
    while (n > (minChars || 3) && estTextWidth(truncLabel(t, n), f) > maxW) n -= 1;
    return { text: truncLabel(t, n), fs: f };
  }

  function smoothPath(pts) {
    if (pts.length < 3) {
      return 'M' + pts.map(function (q) { return q[0].toFixed(1) + ' ' + q[1].toFixed(1); }).join(' L');
    }
    var d = 'M' + pts[0][0].toFixed(1) + ' ' + pts[0][1].toFixed(1);
    for (var i = 0; i < pts.length - 1; i += 1) {
      var p0 = pts[i - 1] || pts[i];
      var p1 = pts[i];
      var p2 = pts[i + 1];
      var p3 = pts[i + 2] || p2;
      var c1x = p1[0] + (p2[0] - p0[0]) / 6;
      var c1y = p1[1] + (p2[1] - p0[1]) / 6;
      var c2x = p2[0] - (p3[0] - p1[0]) / 6;
      var c2y = p2[1] - (p3[1] - p1[1]) / 6;
      d += ' C' + c1x.toFixed(1) + ' ' + c1y.toFixed(1) + ',' + c2x.toFixed(1) + ' '
        + c2y.toFixed(1) + ',' + p2[0].toFixed(1) + ' ' + p2[1].toFixed(1);
    }
    return d;
  }

  /** 极坐标取点（0° 指向正上方，顺时针为正）。 */
  function polar(cx, cy, r, deg) {
    var a = (deg - 90) * Math.PI / 180;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  }

  function arcPath(cx, cy, rOuter, rInner, a0, a1) {
    var large = (a1 - a0) > 180 ? 1 : 0;
    var p0 = polar(cx, cy, rOuter, a0);
    var p1 = polar(cx, cy, rOuter, a1);
    if (rInner <= 0) {
      return 'M' + cx.toFixed(1) + ' ' + cy.toFixed(1)
        + ' L' + p0[0].toFixed(1) + ' ' + p0[1].toFixed(1)
        + ' A' + rOuter.toFixed(1) + ' ' + rOuter.toFixed(1) + ' 0 ' + large + ' 1 '
        + p1[0].toFixed(1) + ' ' + p1[1].toFixed(1) + ' Z';
    }
    var q0 = polar(cx, cy, rInner, a1);
    var q1 = polar(cx, cy, rInner, a0);
    return 'M' + p0[0].toFixed(1) + ' ' + p0[1].toFixed(1)
      + ' A' + rOuter.toFixed(1) + ' ' + rOuter.toFixed(1) + ' 0 ' + large + ' 1 '
      + p1[0].toFixed(1) + ' ' + p1[1].toFixed(1)
      + ' L' + q0[0].toFixed(1) + ' ' + q0[1].toFixed(1)
      + ' A' + rInner.toFixed(1) + ' ' + rInner.toFixed(1) + ' 0 ' + large + ' 0 '
      + q1[0].toFixed(1) + ' ' + q1[1].toFixed(1) + ' Z';
  }

  /**
   * 统计图渲染：纯 SVG。画布、缩略图、静态导出、PPTX 截图四处的几何完全一致。
   * 支持 bar / hbar / line / area / stackedArea / pie / donut / rose / radar /
   * scatter / bubble / funnel / gauge / progress，柱状图另可开 grouped / stacked。
   */
  function chartSvg(props) {
    var p = props || {};
    var W = clamp(num(p.width, 640), 120, 4000);
    var H = clamp(num(p.height, 360), 100, 4000);
    var kind = normKind(p.kind || 'bar');
    var colors = chartColors(p);
    var d = chartData(p, kind);
    var fmt = p.valueFormat || 'auto';
    var showValues = p.showValues !== false && fmt !== 'none';
    var titleColor = safeColor(p.titleColor, '#1f2328');
    var titleSize = clamp(num(p.titleSize, 17), 8, 80);
    var titleAlign = p.titleAlign || 'center';
    var labelColor = safeColor(p.labelColor, '#667085');
    var valueColor = safeColor(p.valueColor, '#475467');
    var gridColor = safeColor(p.gridColor, '#e6e9ee');
    var axisColor = safeColor(p.axisColor, '#d0d5dd');
    var showGrid = p.showGrid !== false;
    var showAxis = p.showAxis !== false;
    var gridCount = clamp(Math.round(num(p.gridCount, 4)), 1, 12);
    var barRadius = clamp(num(p.barRadius, 2), 0, 40);
    var barGap = clamp(num(p.barGap, 0.34), 0, 0.9);
    var lineWidth = clamp(num(p.lineWidth, 2.5), 0.5, 20);
    var showPoints = p.showPoints !== false;
    var areaOpacity = clamp(num(p.areaOpacity, 0.22), 0.02, 1);
    var tickFs = clamp(num(p.fontSize, 12), 6, 48);
    var pieFamily = kind === 'pie' || kind === 'donut' || kind === 'rose';
    var legendPos = p.legendPos || (pieFamily ? 'right' : 'top');
    if (p.showLegend === false) legendPos = 'none';

    // 论文级统计图形：数据读法与常规图表不同（第一列分组、其余单元格是样本），先在这里规约好
    var STAT_KINDS = { box: 1, violin: 1, hist: 1, ecdf: 1, heatmap: 1, errorbar: 1 };
    var statKind = STAT_KINDS[kind] === 1;
    var errList = kind === 'errorbar' ? errorRows(p) : [];
    var statList = statKind && (kind === 'box' || kind === 'violin' || kind === 'hist' || kind === 'ecdf')
      ? statGroups(p) : [];
    // 直方图 / 累积曲线：表里没有重复的分组名时，把整表数值并成一个样本集合（才符合「一堆观测值」的直觉）
    if ((kind === 'hist' || kind === 'ecdf') && statList.length > 1
      && !statList.some(function (g) { return g.rows > 1; })) {
      var pool = [];
      statList.forEach(function (g) { pool = pool.concat(g.values); });
      statList = [{ name: String(p.seriesName || '样本'), values: pool, rows: statList.length }];
    }

    // ---- 统计层（重复样本 → 误差棒 / 显著性 / 拟合线）：在下面各 kind 绘制完成后统一叠加
    var ERR_KINDS = { bar: 1, hbar: 1, line: 1, area: 1, box: 1, violin: 1 };
    var FIT_KINDS = { scatter: 1, bubble: 1, line: 1, area: 1 };
    var CAT_KINDS = { bar: 1, hbar: 1, line: 1, area: 1 };
    var errorType = { sd: 1, sem: 1, ci95: 1 }[String(p.errorType || '')] ? String(p.errorType) : 'none';
    var compareList = parseCompare(p.compare);
    var sigCorrect = p.sigCorrect === 'holm' ? 'holm' : 'none';
    var fitType = { linear: 1, quad: 1, cubic: 1, exp: 1 }[String(p.fitType || '')] ? String(p.fitType) : 'none';
    var sigColor = safeColor(p.sigColor, '#475467');
    var fitColor = safeColor(p.fitColor, '#7b8794');
    var fitWidth = clamp(num(p.fitWidth, 2), 0.5, 12);
    var fitShowEq = p.fitShowEq !== false;
    var fitShowR2 = p.fitShowR2 !== false;
    var wantStat = errorType !== 'none' || compareList.length > 0 || fitType !== 'none';

    var allGroups = statGroups(p);
    var statByName = {};
    allGroups.forEach(function (g) { statByName[g.name] = g; });
    var groupStatsList = allGroups.map(function (g) {
      var st = sampleStats(g.values);
      st.name = g.name; st.values = g.values; st.rows = g.rows;
      return st;
    });
    // 常规类目图：只有「开了统计层 + 确有重复样本」才按分组聚合，普通类目图读法不受影响
    var hasRepeats = groupStatsList.some(function (g) { return g.n > 1; });
    var aggApplied = wantStat && CAT_KINDS[kind] === 1
      && groupStatsList.length >= 2 && hasRepeats;
    if (aggApplied) {
      d = {
        rows: groupStatsList.map(function (g) { return [g.name, g.mean]; }),
        labels: groupStatsList.map(function (g) { return g.name; }),
        names: [String(p.seriesName || '均值')],
        values: [groupStatsList.map(function (g) { return g.mean; })],
        colCount: 2,
      };
    }
    // 误差棒图：开了误差类型且同名分组有重复样本时，把手填误差换成样本重算的 均值 ± SD/SEM/CI
    if (kind === 'errorbar' && errorType !== 'none') {
      errList = errList.map(function (o) {
        var g = statByName[o.name];
        if (g && g.values.length > 1) {
          var st = sampleStats(g.values);
          return { name: o.name, mean: st.mean, err: errHalf(st, errorType), values: g.values, stat: st };
        }
        return o;
      });
    }

    // ---- 显著性：对选定分组对自动跑 Welch t 检验（可 Holm 校正），手填 p / 星号优先
    var sigGroups = null;
    if (kind === 'box' || kind === 'violin') sigGroups = statList;
    else if (kind === 'errorbar') sigGroups = errList;
    else if (aggApplied) sigGroups = groupStatsList;
    var sigItems = [];
    var sigLevels = 0;
    if (sigGroups && sigGroups.length >= 2 && compareList.length) {
      var idxByName = {};
      sigGroups.forEach(function (g, i) { if (idxByName[g.name] === undefined) idxByName[g.name] = i; });
      var raw = [];
      compareList.forEach(function (it) {
        var ai = idxByName[it.a];
        var bi = idxByName[it.b];
        if (ai === undefined || bi === undefined || ai === bi) return;
        var entry = { ai: ai, bi: bi, p: null, text: null, manual: false };
        if (it.stars) { entry.text = it.stars; entry.manual = true; }
        else if (it.p !== null) { entry.p = it.p; entry.manual = true; }
        else {
          var wt = welchT(sigGroups[ai].values || [], sigGroups[bi].values || []);
          if (wt) entry.p = wt.p;
        }
        raw.push(entry);
      });
      // Holm 只校正自动算出的 p；手填 p / 星号是用户明确覆盖，不参与校正
      if (sigCorrect === 'holm') {
        var autoIdx = [];
        raw.forEach(function (e, i) { if (!e.manual && e.p !== null) autoIdx.push(i); });
        var adj = holmAdjust(autoIdx.map(function (i) { return raw[i].p; }));
        autoIdx.forEach(function (i, k) { raw[i].p = adj[k]; });
      }
      raw.forEach(function (e) {
        if (e.text === null) e.text = sigStars(e.p === null ? NaN : e.p);
        sigItems.push(e);
      });
      // 贪心分层：跨度小的放内层，避免括号互相压叠
      var placed = [];
      sigItems.slice().sort(function (x, y) {
        return Math.abs(x.bi - x.ai) - Math.abs(y.bi - y.ai);
      }).forEach(function (e) {
        var lo = Math.min(e.ai, e.bi);
        var hi = Math.max(e.ai, e.bi);
        var lv = 0;
        for (;;) {
          var clash = false;
          for (var q = 0; q < placed.length; q += 1) {
            if (placed[q].lv === lv && !(hi < placed[q].lo || lo > placed[q].hi)) { clash = true; break; }
          }
          if (!clash) break;
          lv += 1;
        }
        placed.push({ lv: lv, lo: lo, hi: hi });
        e.level = lv;
        if (lv + 1 > sigLevels) sigLevels = lv + 1;
      });
    }
    var showSig = sigItems.length > 0 && kind !== 'hbar';

    // 箱线 / 小提琴 / 误差棒的类目轴 = 分组名（长表里同名行会被并成一组，所以不能直接用每行的第一列）
    if (kind === 'box' || kind === 'violin' || kind === 'errorbar') {
      var catList = kind === 'errorbar' ? errList : statList;
      d = {
        rows: catList.map(function (o) { return [o.name, 0]; }),
        labels: catList.map(function (o) { return o.name; }),
        names: [String(p.seriesName || '数值')],
        values: [catList.map(function (o) {
          if (o.mean !== undefined) return o.mean;
          var s = o.values;
          var sum2 = 0;
          for (var k2 = 0; k2 < s.length; k2 += 1) sum2 += s[k2];
          return s.length ? sum2 / s.length : 0;
        })],
        colCount: 2,
      };
    }

    var open = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" '
      + 'style="width:100%;height:100%;display:block;" xmlns="http://www.w3.org/2000/svg">';
    var head = '';
    var parts = [];

    function valText(v) { return stripPlus(fmtValue(v, fmt)); }
    function stripPlus(s) { return String(s).replace(/^-0$/, '0'); }
    function emptyChart() {
      return open + head + '<text x="' + (W / 2) + '" y="' + (H / 2) + '" text-anchor="middle" '
        + 'font-size="15" fill="#98a2b3">暂无数据</text></svg>';
    }

    if (p.title) {
      var tx = titleAlign === 'left' ? 16 : (titleAlign === 'right' ? W - 16 : W / 2);
      var ta = titleAlign === 'left' ? 'start' : (titleAlign === 'right' ? 'end' : 'middle');
      head += '<text x="' + tx.toFixed(1) + '" y="' + (titleSize + 6).toFixed(1) + '" text-anchor="'
        + ta + '" font-size="' + titleSize + '" font-weight="600" fill="' + titleColor + '">'
        + esc(p.title) + '</text>';
    }

    if (!d.rows.length) {
      return emptyChart();
    }
    if (statKind && kind !== 'heatmap' && !(kind === 'errorbar' ? errList : statList).length) {
      return emptyChart();   // 有行但没解析出任何数值，同样按空数据画
    }

    // ---- 图例条目
    var legendItems = [];
    if (statKind && kind !== 'heatmap') {
      // 统计图形按「分组名」列图例（热力图的图例是右侧那条渐变色条，见下）
      (kind === 'errorbar' ? errList : statList).forEach(function (o, i) {
        legendItems.push([o.name, pickColor(colors, i)]);
      });
    } else if (pieFamily) {
      d.labels.forEach(function (lb, i) { legendItems.push([lb, pickColor(colors, i)]); });
    } else if (d.names.length > 1) {
      d.names.forEach(function (nm, i) { legendItems.push([nm, pickColor(colors, i)]); });
    }
    if (!legendItems.length || legendItems.length > 12) legendPos = 'none';

    var legendPad = 24;
    var legendBox = { top: 0, bottom: 0, left: 0, right: 0 };
    // 上/下图例：先按「缩短文字 → 换行」的顺序把每一项排进可用宽度，避免系列多/名字长时互相压住
    var legendRows = 1;
    var legendChars = 10;
    if (legendPos === 'top' || legendPos === 'bottom') {
      var lgAvail = W - 40;
      var lgRowsFor = function (chars) {
        var used = 0;
        var rows = 1;
        legendItems.forEach(function (it) {
          var w = 27 + estTextWidth(truncLabel(it[0], chars), tickFs);
          if (used > 0 && used + w > lgAvail) { rows += 1; used = w; } else { used += w; }
        });
        return rows;
      };
      while (legendChars > 4 && lgRowsFor(legendChars) > 1) legendChars -= 1;
      legendRows = lgRowsFor(legendChars);
      legendBox[legendPos] = legendPad + (legendRows - 1) * (tickFs + 8);
    }
    if (legendPos === 'left' || legendPos === 'right') {
      var lgW = 84;
      legendItems.forEach(function (it) {
        lgW = Math.max(lgW, 25 + estTextWidth(truncLabel(it[0], 18), tickFs));
      });
      legendBox[legendPos] = Math.min(Math.round(lgW + 8), Math.max(84, Math.round(W * 0.34)));
    }

    function legendSvg() {
      if (legendPos === 'none') return '';
      var out = '';
      if (legendPos === 'top' || legendPos === 'bottom') {
        var rowH = tickFs + 8;
        var baseY = legendPos === 'top'
          ? (head ? titleSize + 20 : 16)
          : H - 10 - (legendRows - 1) * rowH;
        var row = 0;
        var cx = 20;
        legendItems.forEach(function (it) {
          var txt = truncLabel(it[0], legendChars);
          var w = 27 + estTextWidth(txt, tickFs);
          if (cx > 20 && cx + w > W - 20 && row < legendRows - 1) { row += 1; cx = 20; }
          var y = baseY + row * rowH;
          out += '<rect x="' + cx.toFixed(1) + '" y="' + (y - 9).toFixed(1) + '" width="10" height="10" rx="2" fill="' + it[1] + '"/>'
            + '<text x="' + (cx + 15).toFixed(1) + '" y="' + y.toFixed(1) + '" font-size="' + tickFs
            + '" fill="' + labelColor + '">' + esc(txt) + '</text>';
          cx += w;
        });
        return out;
      }
      var rowH2 = Math.min(20, Math.max(12, (H - 44) / Math.max(1, legendItems.length)));
      var lx = legendPos === 'right' ? W - legendBox.right + 8 : 12;
      var ly0 = Math.max(28, (H - legendItems.length * rowH2) / 2);
      legendItems.forEach(function (it, i) {
        var ly = ly0 + i * rowH2;
        var ft = fitLabel(it[0], Math.max(24, legendBox[legendPos] - 33), tickFs, 4);
        out += '<rect x="' + lx + '" y="' + (ly - 9).toFixed(1) + '" width="10" height="10" rx="2" fill="' + it[1] + '"/>'
          + '<text x="' + (lx + 15) + '" y="' + ly.toFixed(1) + '" font-size="' + ft.fs + '" fill="'
          + labelColor + '">' + esc(ft.text) + '</text>';
      });
      return out;
    }

    var chartLeft = 56 + legendBox.left;
    var chartRight = W - 20 - legendBox.right;

    // ============================================================ 饼 / 环 / 玫瑰
    if (pieFamily) {
      var vals = d.values[0];
      var total = vals.reduce(function (a, b) { return a + (b > 0 ? b : 0); }, 0) || 1;
      var topPad = (head ? titleSize + 20 : 12) + legendBox.top;
      var botPad = 16 + legendBox.bottom;
      var cx = (chartLeft + chartRight) / 2;
      var cy = topPad + (H - topPad - botPad) / 2;
      var rMax = Math.min((chartRight - chartLeft) / 2, (H - topPad - botPad) / 2) - 4;
      var innerRatio = kind === 'donut' ? clamp(num(p.innerRadius, 0.55), 0.05, 0.92) : 0;
      var startAngle = num(p.startAngle, -90);
      var angle = startAngle;
      var roseMax = Math.max.apply(null, vals.concat([1]));
      d.labels.forEach(function (lb, i) {
        var v = vals[i];
        var sweep = (v / total) * 360;
        var r = kind === 'rose'
          ? rMax * Math.sqrt(Math.max(0, v) / roseMax) : rMax;
        var a2 = angle + sweep;
        if (sweep <= 0) { angle = a2; return; }
        var fill = pickColor(colors, i);
        parts.push('<path d="' + arcPath(cx, cy, r, r * innerRatio, angle, a2) + '" fill="' + fill + '"/>');
        if (showValues && sweep > 12) {
          var mid = (angle + a2) / 2;
          var lr = r * (innerRatio > 0 ? (1 + innerRatio) / 2 : 0.68);
          var pt = polar(cx, cy, lr, mid);
          var label = p.pieLabel === 'label' ? lb
            : (p.pieLabel === 'value' ? valText(v) : Math.round((v / total) * 100) + '%');
          parts.push('<text x="' + pt[0].toFixed(1) + '" y="' + pt[1].toFixed(1)
            + '" text-anchor="middle" dominant-baseline="middle" font-size="' + tickFs
            + '" fill="#ffffff">' + esc(label) + '</text>');
        }
        angle = a2;
      });
      if (kind === 'donut' && p.centerText) {
        parts.push('<text x="' + cx.toFixed(1) + '" y="' + (cy + 5).toFixed(1)
          + '" text-anchor="middle" font-size="' + (tickFs + 6) + '" font-weight="600" fill="'
          + valueColor + '">' + esc(p.centerText) + '</text>');
      }
      return open + head + parts.join('') + legendSvg() + '</svg>';
    }

    // ============================================================ 雷达
    if (kind === 'radar') {
      var topPad2 = (head ? titleSize + 20 : 12) + legendBox.top;
      var cx2 = (chartLeft + chartRight) / 2;
      var cy2 = topPad2 + (H - topPad2 - 16 - legendBox.bottom) / 2;
      var rr = Math.min((chartRight - chartLeft) / 2, (H - topPad2 - 16 - legendBox.bottom) / 2) - 24;
      var n = d.labels.length;
      var maxV = num(p.maxValue, 0) || niceMax(Math.max.apply(null, d.values.map(function (arr) {
        return Math.max.apply(null, arr);
      }).concat([1])));
      var rings = gridCount;
      for (var g2 = 1; g2 <= rings; g2 += 1) {
        var pts2 = [];
        for (var a = 0; a < n; a += 1) pts2.push(polar(cx2, cy2, rr * g2 / rings, a * 360 / n));
        parts.push('<polygon points="' + pts2.map(function (q) { return q[0].toFixed(1) + ',' + q[1].toFixed(1); }).join(' ')
          + '" fill="none" stroke="' + gridColor + '"/>');
      }
      for (var a2 = 0; a2 < n; a2 += 1) {
        var ax = polar(cx2, cy2, rr, a2 * 360 / n);
        parts.push('<line x1="' + cx2.toFixed(1) + '" y1="' + cy2.toFixed(1) + '" x2="' + ax[0].toFixed(1)
          + '" y2="' + ax[1].toFixed(1) + '" stroke="' + gridColor + '"/>');
        var lp = polar(cx2, cy2, rr + 16, a2 * 360 / n);
        parts.push('<text x="' + lp[0].toFixed(1) + '" y="' + (lp[1] + 4).toFixed(1)
          + '" text-anchor="middle" font-size="' + tickFs + '" fill="' + labelColor + '">'
          + esc(truncLabel(d.labels[a2], 8)) + '</text>');
      }
      d.values.forEach(function (arr, si) {
        var pts3 = arr.map(function (v, i) {
          return polar(cx2, cy2, rr * clamp(v / maxV, 0, 1), i * 360 / n);
        });
        var col = pickColor(colors, si);
        if (p.radarFill !== false) {
          parts.push('<polygon points="' + pts3.map(function (q) { return q[0].toFixed(1) + ',' + q[1].toFixed(1); }).join(' ')
            + '" fill="' + col + '" fill-opacity="' + areaOpacity + '" stroke="' + col
            + '" stroke-width="' + lineWidth + '"/>');
        } else {
          parts.push('<polygon points="' + pts3.map(function (q) { return q[0].toFixed(1) + ',' + q[1].toFixed(1); }).join(' ')
            + '" fill="none" stroke="' + col + '" stroke-width="' + lineWidth + '"/>');
        }
        if (showValues) {
          pts3.forEach(function (q, i) {
            parts.push('<text x="' + q[0].toFixed(1) + '" y="' + (q[1] - 6).toFixed(1)
              + '" text-anchor="middle" font-size="' + Math.max(8, tickFs - 2) + '" fill="' + valueColor
              + '">' + esc(valText(arr[i])) + '</text>');
          });
        }
      });
      return open + head + parts.join('') + legendSvg() + '</svg>';
    }

    // ============================================================ 漏斗
    if (kind === 'funnel') {
      var fvals = d.values[0];
      var fmax = num(p.maxValue, 0) || Math.max.apply(null, fvals.concat([1]));
      var fTop = (head ? titleSize + 20 : 12) + legendBox.top;
      var fBot = H - 16 - legendBox.bottom;
      var fGap = clamp(num(p.funnelGap, 4), 0, 40);
      var rowH = (fBot - fTop) / fvals.length;
      fvals.forEach(function (v, i) {
        var w0 = (chartRight - chartLeft) * clamp((fvals[i - 1] !== undefined ? fvals[i - 1] : v) / fmax, 0, 1);
        if (i === 0) w0 = (chartRight - chartLeft);
        var w1 = (chartRight - chartLeft) * clamp(v / fmax, 0, 1);
        var y0 = fTop + i * rowH + fGap / 2;
        var y1 = fTop + (i + 1) * rowH - fGap / 2;
        var mx = (chartLeft + chartRight) / 2;
        var col = pickColor(colors, i);
        parts.push('<polygon points="' + (mx - w0 / 2).toFixed(1) + ',' + y0.toFixed(1) + ' '
          + (mx + w0 / 2).toFixed(1) + ',' + y0.toFixed(1) + ' '
          + (mx + w1 / 2).toFixed(1) + ',' + y1.toFixed(1) + ' '
          + (mx - w1 / 2).toFixed(1) + ',' + y1.toFixed(1) + '" fill="' + col + '"/>');
        var lbl = d.labels[i] + (showValues ? '  ' + valText(v) : '');
        parts.push('<text x="' + mx.toFixed(1) + '" y="' + ((y0 + y1) / 2 + 4).toFixed(1)
          + '" text-anchor="middle" font-size="' + tickFs + '" fill="#ffffff">' + esc(truncLabel(lbl, 22)) + '</text>');
      });
      return open + head + parts.join('') + '</svg>';
    }

    // ============================================================ 仪表盘
    if (kind === 'gauge') {
      var gMin = num(p.gaugeMin, num(p.minValue, 0));
      var gMax = num(p.gaugeMax, num(p.maxValue, 100));
      if (gMax <= gMin) gMax = gMin + 1;
      var gVal = num(p.value, d.values[0][0]);
      var used = clamp((gVal - gMin) / (gMax - gMin), 0, 1);
      var gTop = (head ? titleSize + 20 : 12) + legendBox.top;
      var cx3 = W / 2;
      var cy3 = gTop + (H - gTop - 24) * 0.82;
      var gr = Math.min(W * 0.38, H - gTop - 40);
      parts.push('<path d="' + arcPath(cx3, cy3, gr, gr * 0.68, -90, 90) + '" fill="' + gridColor + '"/>');
      if (used > 0.001) {
        parts.push('<path d="' + arcPath(cx3, cy3, gr, gr * 0.68, -90, -90 + used * 180) + '" fill="'
          + pickColor(colors, 0) + '"/>');
      }
      if (num(p.gaugeTicks, 0) > 0) {
        var tickN = clamp(Math.round(num(p.gaugeTicks, 5)), 2, 20);
        for (var t = 0; t <= tickN; t += 1) {
          var tv = gMin + (gMax - gMin) * t / tickN;
          var tp = polar(cx3, cy3, gr * 1.06, -90 + (t / tickN) * 180);
          parts.push('<text x="' + tp[0].toFixed(1) + '" y="' + (tp[1] + 4).toFixed(1)
            + '" text-anchor="middle" font-size="' + Math.max(8, tickFs - 1) + '" fill="' + labelColor
            + '">' + esc(valText(tv)) + '</text>');
        }
      }
      parts.push('<text x="' + cx3.toFixed(1) + '" y="' + (cy3 - gr * 0.06).toFixed(1)
        + '" text-anchor="middle" font-size="' + (tickFs * 2.2) + '" font-weight="700" fill="'
        + valueColor + '">' + esc(valText(gVal)) + '</text>');
      if (p.unit) {
        parts.push('<text x="' + cx3.toFixed(1) + '" y="' + (cy3 + tickFs * 1.6).toFixed(1)
          + '" text-anchor="middle" font-size="' + tickFs + '" fill="' + labelColor + '">'
          + esc(p.unit) + '</text>');
      }
      return open + head + parts.join('') + '</svg>';
    }

    // ============================================================ 进度条（排行榜）
    if (kind === 'progress') {
      var pTop = (head ? titleSize + 20 : 12) + legendBox.top;
      var pBot = H - 16 - legendBox.bottom;
      var pMax = num(p.maxValue, 0) || Math.max.apply(null, d.values[0].concat([1]));
      var rowH2 = (pBot - pTop) / d.rows.length;
      var trackH = Math.min(rowH2 * 0.56, 26);
      var nameW = clamp((chartRight - chartLeft) * 0.26, 40, 220);
      d.values[0].forEach(function (v, i) {
        var y = pTop + rowH2 * i + rowH2 / 2;
        var bx = chartLeft + nameW;
        var bw2 = chartRight - bx;
        var col = pickColor(colors, p.colorByCategory !== false ? i : 0);
        parts.push('<text x="' + (chartLeft + nameW - 10).toFixed(1) + '" y="' + (y + 4).toFixed(1)
          + '" text-anchor="end" font-size="' + tickFs + '" fill="' + labelColor + '">'
          + esc(truncLabel(d.labels[i], 14)) + '</text>');
        parts.push('<rect x="' + bx.toFixed(1) + '" y="' + (y - trackH / 2).toFixed(1) + '" width="'
          + bw2.toFixed(1) + '" height="' + trackH.toFixed(1) + '" rx="' + (trackH / 2).toFixed(1)
          + '" fill="' + gridColor + '"/>');
        var frac = clamp(v / pMax, 0, 1);
        if (frac > 0) {
          parts.push('<rect x="' + bx.toFixed(1) + '" y="' + (y - trackH / 2).toFixed(1) + '" width="'
            + (bw2 * frac).toFixed(1) + '" height="' + trackH.toFixed(1) + '" rx="'
            + (trackH / 2).toFixed(1) + '" fill="' + col + '"/>');
        }
        if (showValues) {
          parts.push('<text x="' + (chartRight + 4).toFixed(1) + '" y="' + (y + 4).toFixed(1)
            + '" font-size="' + tickFs + '" fill="' + valueColor + '">' + esc(valText(v)) + '</text>');
        }
      });
      return open + head + parts.join('') + '</svg>';
    }

    // ============================================================ 热力图（矩阵色块 + 色阶）
    if (kind === 'heatmap') {
      var hRows = [];
      d.rows.forEach(function (r) {
        var vals = [];
        r.forEach(function (c, ci) {
          if (ci === 0 && !isNumCell(c)) return;
          if (isNumCell(c)) vals.push(Number(c));
        });
        hRows.push(vals);
      });
      var hCols = Math.max.apply(null, hRows.map(function (r) { return r.length; }).concat([0]));
      var hFlat = [];
      hRows.forEach(function (r) { hFlat = hFlat.concat(r); });
      if (!hCols || !hFlat.length) return emptyChart();
      var hMin = Math.min.apply(null, hFlat);
      var hMax = Math.max.apply(null, hFlat);
      if (hMax === hMin) hMax = hMin + 1;
      var heatName = String(p.heatColors || 'viridis');
      var heat = CHART_HEAT_SCALES[heatName] || CHART_HEAT_SCALES.viridis;
      if (heatName === 'diverging') {
        // 发散色阶以 0 为中心才读得准（正负各占一半色带）
        var hm = Math.max(Math.abs(hMin), Math.abs(hMax));
        hMin = -hm; hMax = hm;
      }
      var barW = p.showLegend === false ? 0 : 46;
      var hBottom = H - (p.xTitle ? 34 : 18) - legendBox.bottom;
      var hLeft = 76 + legendBox.left;
      var gridR = W - 26 - legendBox.right - barW;
      var cw = (gridR - hLeft) / hCols;
      var colNames = [];
      for (var hc = 0; hc < hCols; hc += 1) {
        colNames.push(Array.isArray(p.headers) && p.headers[hc + 1] ? String(p.headers[hc + 1]) : ('第' + (hc + 1) + '列'));
      }
      // 列头向左上斜排：按最长列头预留头顶空间，并限制字数免得首列越出左边界
      var colEstFs = clamp(Math.min(tickFs, cw / 3), 7, 16);
      var hChars = Math.max(4, Math.min(14,
        Math.floor((hLeft + cw / 2 - 4) / Math.max(1, 0.766 * colEstFs * 0.6))));
      var hColPad = 0;
      colNames.forEach(function (cn) {
        hColPad = Math.max(hColPad, estTextWidth(truncLabel(cn, hChars), colEstFs) * 0.643 + 8);
      });
      var hTop = (head ? titleSize + 20 : 12) + legendBox.top + hColPad;
      hTop = Math.min(hTop, hBottom - Math.max(24, hRows.length * 12));
      var chh = (hBottom - hTop) / hRows.length;
      var cellFs = clamp(Math.min(tickFs, cw / 3, chh / 2), 7, 16);
      hRows.forEach(function (r, ri) {
        var y = hTop + chh * ri;
        parts.push('<text x="' + (hLeft - 8).toFixed(1) + '" y="' + (y + chh / 2 + 4).toFixed(1)
          + '" text-anchor="end" font-size="' + cellFs + '" fill="' + labelColor + '">'
          + esc(truncLabel(String((d.rows[ri] || [])[0] === undefined ? ri + 1 : (d.rows[ri] || [])[0]), 10)) + '</text>');
        for (var hc2 = 0; hc2 < hCols; hc2 += 1) {
          if (hc2 >= r.length) continue;
          var t2 = (r[hc2] - hMin) / ((hMax - hMin) || 1);
          var cx2 = hLeft + cw * hc2;
          parts.push('<rect x="' + cx2.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + (cw + 0.5).toFixed(1)
            + '" height="' + (chh + 0.5).toFixed(1) + '" fill="' + mixColors(heat, t2) + '"'
            + (showGrid ? ' stroke="#ffffff" stroke-width="1"' : '') + '/>');
          if (showValues && Math.min(cw, chh) > 24) {
            parts.push('<text x="' + (cx2 + cw / 2).toFixed(1) + '" y="' + (y + chh / 2 + 4).toFixed(1)
              + '" text-anchor="middle" font-size="' + cellFs + '" fill="' + (t2 > 0.6 ? '#ffffff' : '#333333')
              + '">' + esc(stripPlus(fmtValue(r[hc2], fmt))) + '</text>');
          }
        }
      });
      colNames.forEach(function (cn, i) {
        var cx3 = hLeft + cw * i + cw / 2;
        parts.push('<text x="' + cx3.toFixed(1) + '" y="' + (hTop - 8).toFixed(1) + '" text-anchor="end" font-size="' + cellFs
          + '" fill="' + labelColor + '" transform="rotate(-40 ' + cx3.toFixed(1) + ' ' + (hTop - 8).toFixed(1)
          + ')">' + esc(truncLabel(cn, hChars)) + '</text>');
      });
      if (barW) {
        // 右侧渐变色条：上端最大值、下端最小值
        var bx2 = gridR + 26;
        var steps2 = 24;
        for (var s2 = 0; s2 < steps2; s2 += 1) {
          parts.push('<rect x="' + bx2.toFixed(1) + '" y="' + (hTop + (hBottom - hTop) * s2 / steps2).toFixed(1)
            + '" width="14" height="' + ((hBottom - hTop) / steps2 + 0.6).toFixed(1) + '" fill="'
            + mixColors(heat, 1 - s2 / (steps2 - 1)) + '"/>');
        }
        parts.push('<rect x="' + bx2.toFixed(1) + '" y="' + hTop.toFixed(1) + '" width="14" height="'
          + (hBottom - hTop).toFixed(1) + '" fill="none" stroke="' + axisColor + '"/>');
        [hMax, (hMin + hMax) / 2, hMin].forEach(function (v3, i3) {
          parts.push('<text x="' + (bx2 + 20) + '" y="' + (hTop + (hBottom - hTop) * i3 / 2 + 4).toFixed(1)
            + '" font-size="' + Math.max(8, tickFs - 1) + '" fill="' + labelColor + '">'
            + esc(stripPlus(fmtValue(v3, fmt))) + '</text>');
        });
      }
      if (p.xTitle) {
        parts.push('<text x="' + ((hLeft + gridR) / 2).toFixed(1) + '" y="' + (H - legendBox.bottom - 4)
          + '" text-anchor="middle" font-size="' + tickFs + '" fill="' + labelColor + '">' + esc(p.xTitle) + '</text>');
      }
      if (p.yTitle) {
        parts.push('<text x="16" y="' + ((hTop + hBottom) / 2).toFixed(1) + '" text-anchor="middle" font-size="'
          + tickFs + '" fill="' + labelColor + '" transform="rotate(-90 16 ' + ((hTop + hBottom) / 2).toFixed(1)
          + ')">' + esc(p.yTitle) + '</text>');
      }
      return open + head + parts.join('') + '</svg>';
    }

    // ============================================================ 经验累积分布（ECDF）
    if (kind === 'ecdf') {
      var eAll = [];
      statList.forEach(function (g) { eAll = eAll.concat(g.values); });
      var eRange = niceRange(Math.min.apply(null, eAll), Math.max.apply(null, eAll), Math.max(2, gridCount));
      if (num(p.minValue, 0)) eRange.lo = num(p.minValue, 0);
      if (num(p.maxValue, 0)) eRange.hi = num(p.maxValue, 0);
      var eTop = (head ? titleSize + 20 : 12) + legendBox.top;
      var eBottom = H - (p.xTitle ? 34 : 18) - legendBox.bottom;
      var eLeft = 62 + (p.yTitle ? 18 : 0) + legendBox.left;
      var eRight = W - 20 - legendBox.right;
      var eW = Math.max(20, eRight - eLeft);
      var eH = Math.max(20, eBottom - eTop);
      var eSpan = (eRange.hi - eRange.lo) || 1;
      function eX(v) { return eLeft + (v - eRange.lo) / eSpan * eW; }
      function eY(q) { return eBottom - clamp(q, 0, 1) * eH; }
      var eStep = eRange.step > 0 ? eRange.step : eSpan;
      var eTicks = Math.max(1, Math.round(eSpan / eStep));
      for (var e1 = 0; e1 <= eTicks; e1 += 1) {
        var ex = eX(eRange.lo + eStep * e1);
        var ev = eRange.lo + eStep * e1;
        if (showGrid) parts.push('<line x1="' + ex.toFixed(1) + '" y1="' + eTop.toFixed(1) + '" x2="' + ex.toFixed(1)
          + '" y2="' + eBottom.toFixed(1) + '" stroke="' + gridColor + '"/>');
        parts.push('<text x="' + ex.toFixed(1) + '" y="' + (eBottom + 16) + '" text-anchor="middle" font-size="'
          + Math.max(8, tickFs - 1) + '" fill="' + labelColor + '">' + esc(valText(ev)) + '</text>');
      }
      for (var e2 = 0; e2 <= 4; e2 += 1) {
        var ey = eY(e2 / 4);
        if (showGrid) parts.push('<line x1="' + eLeft.toFixed(1) + '" y1="' + ey.toFixed(1) + '" x2="' + eRight.toFixed(1)
          + '" y2="' + ey.toFixed(1) + '" stroke="' + gridColor + '"/>');
        parts.push('<text x="' + (eLeft - 8) + '" y="' + (ey + 4).toFixed(1) + '" text-anchor="end" font-size="'
          + Math.max(8, tickFs - 1) + '" fill="' + labelColor + '">' + (e2 * 25) + '%</text>');
      }
      if (showAxis) {
        parts.push('<line x1="' + eLeft + '" y1="' + eTop + '" x2="' + eLeft + '" y2="' + eBottom
          + '" stroke="' + axisColor + '"/>');
        parts.push('<line x1="' + eLeft + '" y1="' + eBottom + '" x2="' + eRight + '" y2="' + eBottom
          + '" stroke="' + axisColor + '"/>');
        if (p.axisBox) {
          parts.push('<line x1="' + eLeft + '" y1="' + eTop + '" x2="' + eRight + '" y2="' + eTop
            + '" stroke="' + axisColor + '"/>');
          parts.push('<line x1="' + eRight + '" y1="' + eTop + '" x2="' + eRight + '" y2="' + eBottom
            + '" stroke="' + axisColor + '"/>');
        }
      }
      statList.forEach(function (g, gi) {
        var col = pickColor(colors, gi);
        var s3 = g.values.slice().sort(function (a, b) { return a - b; });
        var dpath = ['M' + eX(eRange.lo).toFixed(1) + ' ' + eY(0).toFixed(1)];
        var py = eY(0);
        s3.forEach(function (v, i) {
          var px = eX(v);
          var ny = eY((i + 1) / s3.length);
          dpath.push('L' + px.toFixed(1) + ' ' + py.toFixed(1));
          dpath.push('L' + px.toFixed(1) + ' ' + ny.toFixed(1));
          py = ny;
          if (showPoints && s3.length <= 120) {
            parts.push('<circle cx="' + px.toFixed(1) + '" cy="' + py.toFixed(1) + '" r="2.4" fill="' + col + '"/>');
          }
        });
        dpath.push('L' + eX(eRange.hi).toFixed(1) + ' ' + py.toFixed(1));
        parts.push('<path d="' + dpath.join(' ') + '" fill="none" stroke="' + col + '" stroke-width="' + lineWidth
          + '" stroke-linejoin="round" stroke-linecap="round"/>');
      });
      if (p.xTitle) {
        parts.push('<text x="' + ((eLeft + eRight) / 2).toFixed(1) + '" y="' + (H - legendBox.bottom - 4)
          + '" text-anchor="middle" font-size="' + tickFs + '" fill="' + labelColor + '">' + esc(p.xTitle) + '</text>');
      }
      if (p.yTitle) {
        parts.push('<text x="16" y="' + ((eTop + eBottom) / 2).toFixed(1) + '" text-anchor="middle" font-size="'
          + tickFs + '" fill="' + labelColor + '" transform="rotate(-90 16 ' + ((eTop + eBottom) / 2).toFixed(1)
          + ')">' + esc(p.yTitle) + '</text>');
      }
      return open + head + parts.join('') + legendSvg() + '</svg>';
    }

    // ============================================================ 直方图（分箱 + 可选核密度曲线）
    if (kind === 'hist') {
      var hAll = [];
      statList.forEach(function (g) { hAll = hAll.concat(g.values); });
      var hLo = Math.min.apply(null, hAll);
      var hHi = Math.max.apply(null, hAll);
      if (!(hHi > hLo)) hHi = hLo + 1;
      var binN = clamp(Math.round(num(p.bins, 0)) || (Math.ceil(Math.log(Math.max(2, hAll.length)) / Math.LN2) + 1), 3, 40);
      var binW = (hHi - hLo) / binN;
      var dens = p.density === true;
      var sets = statList.map(function (g) {
        var counts = [];
        for (var z = 0; z < binN; z += 1) counts.push(0);
        g.values.forEach(function (v) {
          counts[clamp(Math.floor((v - hLo) / binW), 0, binN - 1)] += 1;
        });
        return dens ? counts.map(function (c) { return c / (g.values.length * binW); }) : counts;
      });
      var maxH = 0;
      sets.forEach(function (cs) { cs.forEach(function (c) { if (c > maxH) maxH = c; }); });
      maxH = maxH || 1;
      var gTop = (head ? titleSize + 20 : 12) + legendBox.top;
      var gBottom = H - (p.xTitle ? 34 : 18) - legendBox.bottom;
      var gLeft = 62 + (p.yTitle ? 18 : 0) + legendBox.left;
      var gRight = W - 20 - legendBox.right;
      var gW = Math.max(20, gRight - gLeft);
      var gH = Math.max(20, gBottom - gTop);
      var xLo = num(p.minValue, 0) || hLo;
      var xHi = num(p.maxValue, 0) || hHi;
      if (!(xHi > xLo)) xHi = xLo + 1;
      var topV = niceMax(maxH);
      function gX(v) { return gLeft + (v - xLo) / (xHi - xLo) * gW; }
      function gY(v) { return gBottom - clamp(v / topV, 0, 1) * gH; }
      function tickText(v) { return dens ? String(Math.round(v * 1000) / 1000) : valText(v); }
      for (var y1 = 0; y1 <= gridCount; y1 += 1) {
        var yv1 = topV * y1 / gridCount;
        var yy4 = gY(yv1);
        if (showGrid) parts.push('<line x1="' + gLeft.toFixed(1) + '" y1="' + yy4.toFixed(1) + '" x2="' + gRight.toFixed(1)
          + '" y2="' + yy4.toFixed(1) + '" stroke="' + gridColor + '"/>');
        parts.push('<text x="' + (gLeft - 8) + '" y="' + (yy4 + 4).toFixed(1) + '" text-anchor="end" font-size="'
          + Math.max(8, tickFs - 1) + '" fill="' + labelColor + '">' + esc(tickText(yv1)) + '</text>');
      }
      var xEvery = Math.max(1, Math.ceil(binN / 8));
      for (var y2 = 0; y2 <= binN; y2 += xEvery) {
        var xv2 = hLo + binW * y2;
        var xx4 = gX(xv2);
        parts.push('<text x="' + xx4.toFixed(1) + '" y="' + (gBottom + 16) + '" text-anchor="middle" font-size="'
          + Math.max(8, tickFs - 1) + '" fill="' + labelColor + '">' + esc(valText(xv2)) + '</text>');
      }
      if (showAxis) {
        parts.push('<line x1="' + gLeft + '" y1="' + gTop + '" x2="' + gLeft + '" y2="' + gBottom
          + '" stroke="' + axisColor + '"/>');
        parts.push('<line x1="' + gLeft + '" y1="' + gBottom + '" x2="' + gRight + '" y2="' + gBottom
          + '" stroke="' + axisColor + '"/>');
        if (p.axisBox) {
          parts.push('<line x1="' + gLeft + '" y1="' + gTop + '" x2="' + gRight + '" y2="' + gTop
            + '" stroke="' + axisColor + '"/>');
          parts.push('<line x1="' + gRight + '" y1="' + gTop + '" x2="' + gRight + '" y2="' + gBottom
            + '" stroke="' + axisColor + '"/>');
        }
      }
      statList.forEach(function (g, gi) {
        var col = pickColor(colors, gi);
        var multi = statList.length > 1;
        sets[gi].forEach(function (c, bi) {
          if (!(c > 0)) return;
          var x0 = gX(hLo + binW * bi);
          var x1 = gX(hLo + binW * (bi + 1));
          var y0 = gY(c);
          parts.push('<rect x="' + x0.toFixed(1) + '" y="' + y0.toFixed(1) + '" width="' + Math.max(1, x1 - x0 - (multi ? 0 : 1)).toFixed(1)
            + '" height="' + Math.max(0, gBottom - y0).toFixed(1) + '" fill="' + col + '" fill-opacity="'
            + (multi ? 0.45 : 0.85) + '"' + (multi ? ' stroke="' + col + '"' : '') + '/>');
        });
      });
      if (p.kdeCurve !== false) {
        statList.forEach(function (g, gi) {
          var curve = kdeCurve(g.values, hLo, hHi, 120);
          if (!curve.length) return;
          var kMax = 0;
          curve.forEach(function (q) { if (q[1] > kMax) kMax = q[1]; });
          if (!(kMax > 0)) return;
          var scale = dens ? 1 : (maxH / kMax);
          var dd = curve.map(function (q, i) {
            return (i ? 'L' : 'M') + gX(q[0]).toFixed(1) + ' ' + gY(q[1] * scale).toFixed(1);
          }).join(' ');
          parts.push('<path d="' + dd + '" fill="none" stroke="' + pickColor(colors, gi) + '" stroke-width="'
            + clamp(lineWidth, 1, 5) + '" stroke-linejoin="round" stroke-linecap="round"/>');
        });
      }
      if (p.xTitle) {
        parts.push('<text x="' + ((gLeft + gRight) / 2).toFixed(1) + '" y="' + (H - legendBox.bottom - 4)
          + '" text-anchor="middle" font-size="' + tickFs + '" fill="' + labelColor + '">' + esc(p.xTitle) + '</text>');
      }
      if (p.yTitle) {
        parts.push('<text x="16" y="' + ((gTop + gBottom) / 2).toFixed(1) + '" text-anchor="middle" font-size="'
          + tickFs + '" fill="' + labelColor + '" transform="rotate(-90 16 ' + ((gTop + gBottom) / 2).toFixed(1)
          + ')">' + esc(p.yTitle) + '</text>');
      }
      return open + head + parts.join('') + legendSvg() + '</svg>';
    }

    // ============================================================ 直角坐标系家族
    var stacked = p.stacked === true || kind === 'stackedArea';
    var grouped = p.grouped === true;
    var horizontal = kind === 'hbar';
    var seriesCount = d.values.length;
    var useGrouped = !stacked && (grouped || (seriesCount > 1 && !pieFamily));

    var maxRaw = 0;
    if (stacked) {
      for (var i2 = 0; i2 < d.labels.length; i2 += 1) {
        var sum = 0;
        d.values.forEach(function (arr) { sum += arr[i2]; });
        if (sum > maxRaw) maxRaw = sum;
      }
    } else {
      d.values.forEach(function (arr) {
        var m = Math.max.apply(null, arr);
        if (m > maxRaw) maxRaw = m;
      });
    }
    var yMax = num(p.maxValue, 0) || niceMax(maxRaw);
    var yMin = num(p.minValue, 0);

    // 误差棒（mean ± SD/SEM/95%CI）：先算出来，纵轴范围与各分支绘制共用
    var errBars = [];
    if (errorType !== 'none' && ERR_KINDS[kind] === 1) {
      if (kind === 'box' || kind === 'violin') {
        statList.forEach(function (g, i) {
          var st2 = sampleStats(g.values);
          errBars.push({ i: i, v: st2.mean, half: errHalf(st2, errorType) });
        });
      } else if (aggApplied) {
        groupStatsList.forEach(function (g, i) {
          errBars.push({ i: i, v: g.mean, half: errHalf(g, errorType) });
        });
      }
    }

    // 统计图形的纵轴按样本范围取「好看刻度」，默认不从 0 起（箱线 / 小提琴 / 误差棒都这么读）
    if (statKind) {
      var sVals = [];
      if (kind === 'errorbar') {
        errList.forEach(function (o) { sVals.push(o.mean - o.err, o.mean + o.err); });
      } else {
        statList.forEach(function (g) { sVals = sVals.concat(g.values); });
      }
      errBars.forEach(function (b) { sVals.push(b.v - b.half, b.v + b.half); });
      if (p.zeroBase === true) sVals.push(0);   // 勾了「纵轴从 0 起」就把 0 纳进范围
      var sr = niceRange(Math.min.apply(null, sVals), Math.max.apply(null, sVals), gridCount);
      if (!num(p.maxValue, 0)) yMax = sr.hi;
      if (!num(p.minValue, 0)) yMin = sr.lo;
      if (!num(p.maxValue, 0) && !num(p.minValue, 0)) gridCount = clamp(sr.count, 1, 24);
      if (yMax <= yMin) yMax = yMin + 1;
    } else if (errBars.length && (!num(p.maxValue, 0) || !num(p.minValue, 0))) {
      // 常规图上的误差棒也不能伸出可见范围
      var eHi = -Infinity;
      var eLo = Infinity;
      errBars.forEach(function (b) {
        if (b.v + b.half > eHi) eHi = b.v + b.half;
        if (b.v - b.half < eLo) eLo = b.v - b.half;
      });
      if (!num(p.maxValue, 0)) yMax = niceMax(Math.max(yMax, eHi));
      if (!num(p.minValue, 0)) yMin = Math.min(yMin, eLo);
      if (yMax <= yMin) yMax = yMin + 1;
    }

    // 误差棒按类目索引建表：数值标签要抬到误差棒上沿，且必须画在误差棒之后，否则会被竖线/端帽盖住
    var ebByIndex = {};
    errBars.forEach(function (b) { ebByIndex[b.i] = b; });

    var topM = (head ? titleSize + 22 : 12) + legendBox.top;
    var botM = 34 + (p.xTitle && !horizontal ? 16 : 0) + legendBox.bottom;
    var leftM = 56 + (p.yTitle && !horizontal ? 18 : 0) + legendBox.left;
    var rightM = 20 + legendBox.right;
    // 竖排类目图的 x 轴类目名：槽位放不下时整体改斜排（-35°），
    // 先算出需要多少底部留白，免得标签被裁掉或被轴标题压住
    var xRotate = false;
    var xRotPad = 0;
    var xRotChars = 14;
    var xCatKinds = { bar: 1, line: 1, area: 1, stackedArea: 1, box: 1, violin: 1, errorbar: 1 };
    var preCatN = d.labels.length;
    if (!horizontal && xCatKinds[kind] === 1 && preCatN > 0) {
      var preSlot = (W - rightM - (56 + (p.yTitle ? 18 : 0) + legendBox.left)) / preCatN;
      var preFs = clamp(Math.min(tickFs, Math.round(preSlot / Math.max(2, 2.6))), 7, 18);
      var preMax = 0;
      d.labels.forEach(function (lb) { preMax = Math.max(preMax, estTextWidth(truncLabel(lb, 10), preFs)); });
      if (preMax > preSlot - 2) {
        // 斜排（-35°）向左上伸展：一是不能越出左边距，二是不能吃掉太多底部高度。
        // 两条都满足、且还能显示至少 6 个字时才值得斜排，否则退回截断 + 缩字号的横排
        var wRotAt = function (chars) {
          var w = 0;
          d.labels.forEach(function (lb) { w = Math.max(w, estTextWidth(truncLabel(lb, chars), preFs)); });
          return w;
        };
        var xLeftRoom = 56 + (p.yTitle ? 18 : 0) + legendBox.left + preSlot / 2 - 4;
        while (xRotChars > 4 && wRotAt(xRotChars) * 0.819 > xLeftRoom) xRotChars -= 1;   // cos(35°) ≈ 0.819
        var prePlotH0 = H - topM - (34 + (p.xTitle && !horizontal ? 16 : 0) + legendBox.bottom);
        var rotH = wRotAt(xRotChars) * 0.574 + preFs + 6;   // sin(35°) ≈ 0.574
        if (xRotChars >= 6 && rotH <= prePlotH0 * 0.5) {
          xRotate = true;
          xRotPad = Math.round(rotH);
        }
      }
    }
    if (horizontal) {
      topM = (head ? titleSize + 22 : 12) + legendBox.top;
      leftM = 84 + legendBox.left;
      botM = 34 + (p.xTitle ? 16 : 0) + legendBox.bottom;
    }
    if (showSig) topM += sigLevels * 20 + 14;   // 给显著性括号留出头顶空间
    if (xRotate) botM = Math.max(botM, xRotPad + (p.xTitle ? 16 : 0) + 8);
    var plotL = leftM;
    var plotR = W - rightM;
    var plotT = topM;
    var plotB = H - botM;
    if (plotR - plotL < 40 || plotB - plotT < 40) {
      plotL = 24; plotR = W - 12; plotT = 24; plotB = H - 24;
    }
    var plotW = plotR - plotL;
    var plotH = plotB - plotT;

    function axisValue(v) {
      var lo = horizontal ? 0 : yMin;
      var hi = yMax;
      if (hi <= lo) hi = lo + 1;
      return clamp((v - lo) / (hi - lo), 0, 1);
    }

    // ---- 网格与刻度
    if (horizontal) {
      for (var h2 = 0; h2 <= gridCount; h2 += 1) {
        var gx = plotL + plotW * h2 / gridCount;
        var gv = yMin + (yMax - yMin) * h2 / gridCount;
        if (showGrid) parts.push('<line x1="' + gx.toFixed(1) + '" y1="' + plotT + '" x2="' + gx.toFixed(1)
          + '" y2="' + plotB + '" stroke="' + gridColor + '"/>');
        parts.push('<text x="' + gx.toFixed(1) + '" y="' + (plotB + 16) + '" text-anchor="middle" font-size="'
          + Math.max(8, tickFs - 1) + '" fill="' + labelColor + '">' + esc(valText(gv)) + '</text>');
      }
      if (showAxis) parts.push('<line x1="' + plotL + '" y1="' + plotT + '" x2="' + plotL + '" y2="' + plotB
        + '" stroke="' + axisColor + '"/>');
    } else {
      for (var g3 = 0; g3 <= gridCount; g3 += 1) {
        var gy = plotT + plotH * g3 / gridCount;
        var gv2 = yMin + (yMax - yMin) * (gridCount - g3) / gridCount;
        if (showGrid) parts.push('<line x1="' + plotL + '" y1="' + gy.toFixed(1) + '" x2="' + plotR + '" y2="'
          + gy.toFixed(1) + '" stroke="' + gridColor + '"/>');
        parts.push('<text x="' + (plotL - 8) + '" y="' + (gy + 4).toFixed(1) + '" text-anchor="end" font-size="'
          + Math.max(8, tickFs - 1) + '" fill="' + labelColor + '">' + esc(valText(gv2)) + '</text>');
      }
      if (showAxis) parts.push('<line x1="' + plotL + '" y1="' + plotB + '" x2="' + plotR + '" y2="' + plotB
        + '" stroke="' + axisColor + '"/>');
    }

    var nCat = d.labels.length;
    var slot = (horizontal ? plotH : plotW) / nCat;
    var slotFs = clamp(Math.min(tickFs, Math.round(slot / Math.max(2, 2.6))), 7, 18);
    // 未斜排时的类目名兜底：先减字数、再缩字号，保证每个标签都塞进自己的槽位
    var xCatChars = 10;
    if (!horizontal && !xRotate && xCatKinds[kind] === 1) {
      var wCatAt = function (chars) {
        var w = 0;
        d.labels.forEach(function (lb) { w = Math.max(w, estTextWidth(truncLabel(lb, chars), slotFs)); });
        return w;
      };
      while (xCatChars > 3 && wCatAt(xCatChars) > slot - 2) xCatChars -= 1;
      if (wCatAt(xCatChars) > slot - 2) slotFs = Math.max(7, Math.floor(slotFs * (slot - 2) / wCatAt(xCatChars)));
    }

    // ---- 散点 / 气泡：横轴是数值轴，范围与刻度由 d.xVals 决定
    var isXY = kind === 'scatter' || kind === 'bubble';
    var xVals = isXY ? (d.xVals || []) : [];
    var sizeVals = isXY ? d.sizeVals : null;
    var xMin = 0;
    var xMax = 1;
    if (isXY && xVals.length) {
      var xr = niceRange(Math.min.apply(null, xVals), Math.max.apply(null, xVals), gridCount);
      xMin = xr.lo;
      xMax = xr.hi;
    }
    function sizeAt(i) {
      if (!sizeVals) return 1;
      var sv = sizeVals[i];
      return isFinite(sv) && sv > 0 ? sv : 1;
    }

    // ---- 误差棒（mean ± SD/SEM/95%CI），按类目索引落位；横向图随之横过来画
    var ebStroke = clamp(lineWidth, 1, 4);
    var ebCap = Math.max(6, Math.min(slot * 0.5, 20));
    function errorBarSvg(idx, v, half) {
      if (!(half > 0)) return '';
      if (horizontal) {
        var cy = plotT + slot * idx + slot / 2;
        var xa = plotL + axisValue(clamp(v - half, yMin, yMax)) * plotW;
        var xb = plotL + axisValue(clamp(v + half, yMin, yMax)) * plotW;
        var oh = '<line x1="' + xa.toFixed(1) + '" y1="' + cy.toFixed(1) + '" x2="' + xb.toFixed(1) + '" y2="'
          + cy.toFixed(1) + '" stroke="' + valueColor + '" stroke-width="' + ebStroke + '"/>';
        [xa, xb].forEach(function (cx2) {
          oh += '<line x1="' + cx2.toFixed(1) + '" y1="' + (cy - ebCap / 2).toFixed(1) + '" x2="' + cx2.toFixed(1)
            + '" y2="' + (cy + ebCap / 2).toFixed(1) + '" stroke="' + valueColor + '" stroke-width="' + ebStroke + '"/>';
        });
        return oh;
      }
      var cx = plotL + slot * idx + slot / 2;
      var yt2 = plotB - axisValue(clamp(v + half, yMin, yMax)) * plotH;
      var yb2 = plotB - axisValue(clamp(v - half, yMin, yMax)) * plotH;
      var ov = '<line x1="' + cx.toFixed(1) + '" y1="' + yt2.toFixed(1) + '" x2="' + cx.toFixed(1) + '" y2="'
        + yb2.toFixed(1) + '" stroke="' + valueColor + '" stroke-width="' + ebStroke + '"/>';
      [yt2, yb2].forEach(function (cy3) {
        ov += '<line x1="' + (cx - ebCap / 2).toFixed(1) + '" y1="' + cy3.toFixed(1) + '" x2="' + (cx + ebCap / 2).toFixed(1)
          + '" y2="' + cy3.toFixed(1) + '" stroke="' + valueColor + '" stroke-width="' + ebStroke + '"/>';
      });
      return ov;
    }

    // ---- 显著性括号 + 星号（层级越高越靠上）
    var sigSvgMarkup = '';
    if (showSig) {
      sigItems.forEach(function (e) {
        var x1 = plotL + slot * Math.min(e.ai, e.bi) + slot / 2;
        var x2 = plotL + slot * Math.max(e.ai, e.bi) + slot / 2;
        var yb = plotT - 10 - e.level * 20;
        var arm = 5;
        sigSvgMarkup += '<path d="M' + x1.toFixed(1) + ' ' + yb.toFixed(1)
          + ' V' + (yb - arm).toFixed(1) + ' H' + x2.toFixed(1) + ' V' + yb.toFixed(1)
          + '" fill="none" stroke="' + sigColor + '" stroke-width="1.4"/>';
        sigSvgMarkup += '<text x="' + ((x1 + x2) / 2).toFixed(1) + '" y="' + (yb - arm - 3).toFixed(1)
          + '" text-anchor="middle" font-size="' + Math.max(10, tickFs) + '" font-weight="600" fill="'
          + sigColor + '">' + esc(e.text) + '</text>';
      });
    }

    // ---- 横轴标签：类目图写类目名，散点 / 气泡写数值刻度
    if (isXY) {
      for (var xt2 = 0; xt2 <= gridCount; xt2 += 1) {
        var xtx = plotL + plotW * xt2 / gridCount;
        var xtv = xMin + (xMax - xMin) * xt2 / gridCount;
        if (showGrid) {
          parts.push('<line x1="' + xtx.toFixed(1) + '" y1="' + plotT + '" x2="' + xtx.toFixed(1) + '" y2="'
            + plotB + '" stroke="' + gridColor + '"/>');
        }
        parts.push('<text x="' + xtx.toFixed(1) + '" y="' + (plotB + 16) + '" text-anchor="middle" font-size="'
          + Math.max(8, tickFs - 1) + '" fill="' + labelColor + '">' + esc(valText(xtv)) + '</text>');
      }
    } else {
      d.labels.forEach(function (lb, i) {
        if (horizontal) {
          parts.push('<text x="' + (plotL - 8) + '" y="' + (plotT + slot * i + slot / 2 + 4).toFixed(1)
            + '" text-anchor="end" font-size="' + slotFs + '" fill="' + labelColor + '">'
            + esc(truncLabel(lb, 12)) + '</text>');
        } else if (xRotate) {
          var cxr = plotL + slot * i + slot / 2;
          var lyr = plotB + 12;
          parts.push('<text x="' + cxr.toFixed(1) + '" y="' + lyr.toFixed(1) + '" text-anchor="end" font-size="'
            + slotFs + '" fill="' + labelColor + '" transform="rotate(-35 ' + cxr.toFixed(1) + ' '
            + lyr.toFixed(1) + ')">' + esc(truncLabel(lb, xRotChars)) + '</text>');
        } else {
          parts.push('<text x="' + (plotL + slot * i + slot / 2).toFixed(1) + '" y="' + (plotB + 16)
            + '" text-anchor="middle" font-size="' + slotFs + '" fill="' + labelColor + '">'
            + esc(truncLabel(lb, xCatChars)) + '</text>');
        }
      });
    }

    // ---- 轴标题
    if (p.xTitle) {
      parts.push('<text x="' + ((plotL + plotR) / 2).toFixed(1) + '" y="' + (H - legendBox.bottom - 4)
        + '" text-anchor="middle" font-size="' + tickFs + '" fill="' + labelColor + '">'
        + esc(p.xTitle) + '</text>');
    }
    if (p.yTitle) {
      parts.push('<text x="' + (horizontal ? ((plotL + plotR) / 2) : 16) + '" y="'
        + (horizontal ? (H - legendBox.bottom - 4) : ((plotT + plotB) / 2).toFixed(1))
        + '" text-anchor="middle" font-size="' + tickFs + '" fill="' + labelColor + '"'
        + (horizontal ? '' : ' transform="rotate(-90 16 ' + ((plotT + plotB) / 2).toFixed(1) + ')"')
        + '>' + esc(p.yTitle) + '</text>');
    }

    // ---- 箱线 / 小提琴 / 误差棒（复用上面的类目轴 + 数值轴）
    if (statKind) {
      var yOf = function (v) { return plotB - axisValue(v) * plotH; };
      var bandW2 = slot * clamp(num(p.boxWidth, 0.5), 0.08, 1);
      var capW3 = bandW2 * 0.5;
      var strW = clamp(lineWidth, 1, 4);
      var baseY = yOf(clamp(0, yMin, yMax));
      // 箱线 / 小提琴的数值标签先收集，等误差棒画完再叠上去（误差棒端帽可能压到标签）
      var statLabels = [];
      if (kind === 'errorbar') {
        errList.forEach(function (o, i) {
          var col = pickColor(colors, p.colorByCategory === true ? i : 0);
          var cx4 = plotL + slot * i + slot / 2;
          var yv = yOf(o.mean);
          var yt = yOf(clamp(o.mean + o.err, yMin, yMax));
          var yb = yOf(clamp(o.mean - o.err, yMin, yMax));
          parts.push('<rect x="' + (cx4 - bandW2 / 2).toFixed(1) + '" y="' + Math.min(yv, baseY).toFixed(1) + '" width="'
            + bandW2.toFixed(1) + '" height="' + Math.max(1, Math.abs(baseY - yv)).toFixed(1) + '" rx="'
            + Math.min(barRadius, bandW2 / 2).toFixed(1) + '" fill="' + col + '" fill-opacity="0.85"/>');
          parts.push('<line x1="' + cx4.toFixed(1) + '" y1="' + yt.toFixed(1) + '" x2="' + cx4.toFixed(1) + '" y2="'
            + yb.toFixed(1) + '" stroke="' + valueColor + '" stroke-width="' + strW + '"/>');
          [yt, yb].forEach(function (cy4) {
            parts.push('<line x1="' + (cx4 - capW3 / 2).toFixed(1) + '" y1="' + cy4.toFixed(1) + '" x2="'
              + (cx4 + capW3 / 2).toFixed(1) + '" y2="' + cy4.toFixed(1) + '" stroke="' + valueColor
              + '" stroke-width="' + strW + '"/>');
          });
          if (showValues) {
            var labE = valText(o.mean);
            var ftE = estTextWidth(labE, slotFs) > slot - 4
              ? fitLabel(labE, 2 * (slot - 4), slotFs, 3)
              : { text: labE, fs: slotFs };
            // 槽位太窄、标签比槽位还宽时，隔一个上抬一行错开，避免相邻标签挤在一起
            var staggerE = ftE.text === labE && estTextWidth(labE, ftE.fs) > slot - 4
              ? (i % 2) * (ftE.fs + 3) : 0;
            var lyE = yt - 7 - staggerE;
            if (lyE - ftE.fs < plotT) { staggerE = 0; lyE = yt - 7; }
            if (lyE - ftE.fs < plotT) lyE = yt + ftE.fs + 5;   // 顶到上边界就改画在端帽下方
            parts.push('<text x="' + cx4.toFixed(1) + '" y="' + lyE.toFixed(1) + '" text-anchor="middle" font-size="'
              + ftE.fs + '" fill="' + valueColor + '">' + esc(ftE.text) + '</text>');
          }
        });
      } else if (kind === 'box') {
        statList.forEach(function (g, i) {
          var st = boxStats(g.values);
          if (!st) return;
          var col = pickColor(colors, i);
          var cx5 = plotL + slot * i + slot / 2;
          var x0 = cx5 - bandW2 / 2;
          parts.push('<line x1="' + cx5.toFixed(1) + '" y1="' + yOf(st.hi).toFixed(1) + '" x2="' + cx5.toFixed(1)
            + '" y2="' + yOf(st.lo).toFixed(1) + '" stroke="' + col + '" stroke-width="' + strW + '"/>');
          [st.hi, st.lo].forEach(function (wv) {
            parts.push('<line x1="' + (cx5 - capW3 / 2).toFixed(1) + '" y1="' + yOf(wv).toFixed(1) + '" x2="'
              + (cx5 + capW3 / 2).toFixed(1) + '" y2="' + yOf(wv).toFixed(1) + '" stroke="' + col
              + '" stroke-width="' + strW + '"/>');
          });
          parts.push('<rect x="' + x0.toFixed(1) + '" y="' + yOf(st.q3).toFixed(1) + '" width="' + bandW2.toFixed(1)
            + '" height="' + Math.max(1, yOf(st.q1) - yOf(st.q3)).toFixed(1) + '" rx="'
            + Math.min(barRadius, bandW2 / 4).toFixed(1) + '" fill="' + col + '" fill-opacity="0.16" stroke="' + col
            + '" stroke-width="' + strW + '"/>');
          parts.push('<line x1="' + x0.toFixed(1) + '" y1="' + yOf(st.med).toFixed(1) + '" x2="' + (x0 + bandW2).toFixed(1)
            + '" y2="' + yOf(st.med).toFixed(1) + '" stroke="' + col + '" stroke-width="' + clamp(strW + 0.6, 1.5, 5) + '"/>');
          if (p.showMean) {
            parts.push('<circle cx="' + cx5.toFixed(1) + '" cy="' + yOf(st.mean).toFixed(1)
              + '" r="3" fill="#ffffff" stroke="' + col + '" stroke-width="1.4"/>');
          }
          if (p.showOutliers !== false) {
            st.outliers.forEach(function (ov) {
              parts.push('<circle cx="' + cx5.toFixed(1) + '" cy="' + yOf(ov).toFixed(1)
                + '" r="2.6" fill="none" stroke="' + col + '" stroke-width="1.2" stroke-opacity="0.75"/>');
            });
          }
          if (showValues) {
            var labB = valText(st.med);
            var availB = slot / 2 - capW3 / 2 - 6;
            if (estTextWidth(labB, slotFs) > availB) {
              // 右侧空隙放不下：改画在箱体上方居中
              var ftB = fitLabel(labB, slot - 4, Math.min(slotFs, 11), 3);
              statLabels.push('<text x="' + cx5.toFixed(1) + '" y="'
                + Math.max(plotT + ftB.fs, yOf(st.hi) - 5).toFixed(1) + '" text-anchor="middle" font-size="'
                + ftB.fs + '" fill="' + valueColor + '">' + esc(ftB.text) + '</text>');
            } else {
              statLabels.push('<text x="' + (cx5 + capW3 / 2 + 4).toFixed(1) + '" y="' + (yOf(st.med) + 4).toFixed(1)
                + '" font-size="' + slotFs + '" fill="' + valueColor + '">' + esc(labB) + '</text>');
            }
          }
        });
      } else if (kind === 'violin') {
        statList.forEach(function (g, i) {
          var col = pickColor(colors, i);
          var cx6 = plotL + slot * i + slot / 2;
          var half = bandW2 / 2;
          var curve = kdeCurve(g.values, yMin, yMax, 60);
          var kMax = 0;
          curve.forEach(function (q) { if (q[1] > kMax) kMax = q[1]; });
          if (!(kMax > 0)) return;
          var right = [];
          var leftS = [];
          curve.forEach(function (q) {
            var w = (q[1] / kMax) * half;
            var yy5 = yOf(q[0]);
            right.push([cx6 + w, yy5]);
            leftS.push([cx6 - w, yy5]);
          });
          var poly = right.concat(leftS.reverse());
          parts.push('<polygon points="' + poly.map(function (q) {
            return q[0].toFixed(1) + ',' + q[1].toFixed(1);
          }).join(' ') + '" fill="' + col + '" fill-opacity="0.28" stroke="' + col + '" stroke-width="'
            + clamp(strW * 0.8, 0.8, 3) + '" stroke-linejoin="round"/>');
          var st2 = boxStats(g.values);
          if (st2) {
            var iw = Math.max(4, bandW2 * 0.16);
            parts.push('<rect x="' + (cx6 - iw / 2).toFixed(1) + '" y="' + yOf(st2.q3).toFixed(1) + '" width="' + iw.toFixed(1)
              + '" height="' + Math.max(1, yOf(st2.q1) - yOf(st2.q3)).toFixed(1)
              + '" fill="#ffffff" fill-opacity="0.85" stroke="' + valueColor + '" stroke-width="1"/>');
            parts.push('<line x1="' + (cx6 - iw / 2).toFixed(1) + '" y1="' + yOf(st2.med).toFixed(1) + '" x2="'
              + (cx6 + iw / 2).toFixed(1) + '" y2="' + yOf(st2.med).toFixed(1) + '" stroke="' + valueColor
              + '" stroke-width="2"/>');
            if (showValues) {
              var labV2 = valText(st2.med);
              var availV2 = slot / 2 - half - 6;
              if (estTextWidth(labV2, slotFs) > availV2) {
                var ftV2 = fitLabel(labV2, slot - 4, Math.min(slotFs, 11), 3);
                statLabels.push('<text x="' + cx6.toFixed(1) + '" y="'
                  + Math.max(plotT + ftV2.fs, yOf(st2.hi) - 5).toFixed(1) + '" text-anchor="middle" font-size="'
                  + ftV2.fs + '" fill="' + valueColor + '">' + esc(ftV2.text) + '</text>');
              } else {
                statLabels.push('<text x="' + (cx6 + half + 4).toFixed(1) + '" y="' + (yOf(st2.med) + 4).toFixed(1)
                  + '" font-size="' + slotFs + '" fill="' + valueColor + '">' + esc(labV2) + '</text>');
              }
            }
          }
        });
      }
      if ((kind === 'box' || kind === 'violin') && errBars.length) {
        errBars.forEach(function (b) { parts.push(errorBarSvg(b.i, b.v, b.half)); });
      }
      if (statLabels.length) parts.push(statLabels.join(''));
      return open + head + parts.join('') + legendSvg() + sigSvgMarkup + '</svg>';
    }

    // ---- 柱状 / 条形
    if (kind === 'bar' || kind === 'hbar') {
      var bandW = slot * (1 - barGap);
      var groupW = useGrouped ? bandW / seriesCount : bandW;
      var stackAcc = d.labels.map(function () { return 0; });
      // 数值标签先收集，等柱子与误差棒全部画完再统一叠上去：既躲开误差棒的竖线/端帽，
      // 也躲开堆叠图中「上一段标签被下一段柱体盖住」的毛病
      var valueLabels = [];
      d.values.forEach(function (arr, si) {
        arr.forEach(function (v, i) {
          var col = pickColor(colors, p.colorByCategory === true ? i : si);
          var frac = axisValue(v);
          var len = Math.abs(frac) * (horizontal ? plotW : plotH);
          var start = horizontal
            ? plotL + axisValue(0) * plotW
            : plotB - axisValue(0) * plotH;
          var offsetStack = stacked ? (stackAcc[i] / (yMax - yMin || 1)) * (horizontal ? plotW : plotH) : 0;
          if (stacked) stackAcc[i] += Math.abs(v) * (v >= 0 ? 1 : -1);
          // 非堆叠时柱子需以槽位中心对齐（标签/误差棒/显著性括号都画在 slot 中心）；
          // 多系列分组时 0.04 是把 0.92 宽的柱体在 groupW 槽内居中：(1 - 0.92) / 2。
          var off = stacked ? offsetStack : (useGrouped ? si * groupW + groupW * 0.04 : 0);
          var eb = stacked ? null : ebByIndex[i];   // 该类目的误差棒（有就把标签让到它外面）
          if (horizontal) {
            var yy = plotT + slot * i + (slot - bandW) / 2 + off;
            var hh = stacked ? len : (useGrouped ? groupW * 0.92 : bandW);
            parts.push('<rect x="' + (v >= 0 ? start + offsetStack * (stacked ? 1 : 0) : start - offsetStack - len).toFixed(1)
              + '" y="' + yy.toFixed(1) + '" width="' + Math.max(0, len).toFixed(1) + '" height="'
              + Math.max(1, hh).toFixed(1) + '" rx="' + Math.min(barRadius, hh / 2).toFixed(1) + '" fill="' + col + '"/>');
            if (showValues && len > 18) {
              var labH = valText(v);
              var labFsH = Math.max(8, Math.min(tickFs - 1, Math.round(hh * 0.9)));
              var wH = estTextWidth(labH, labFsH);
              var cyH = yy + hh / 2 + 4;
              var tipX = start + axisValue(clamp(v + (eb ? eb.half : 0), yMin, yMax)) * plotW;
              var xOut = v >= 0 ? tipX + 6 : tipX - 6;
              var aOut = v >= 0 ? 'start' : 'end';
              var fits = v >= 0 ? (xOut + wH <= plotR - 2) : (xOut - wH >= plotL + 2);
              if (fits) {
                valueLabels.push('<text x="' + xOut.toFixed(1) + '" y="' + cyH.toFixed(1) + '" text-anchor="' + aOut
                  + '" font-size="' + labFsH + '" fill="' + valueColor + '">' + esc(labH) + '</text>');
              } else {
                // 条形过长、标签会被右边界裁掉：挪进条形内部，用白字保证可读
                var xIn2 = v >= 0 ? start + len - 6 : start - len + 6;
                if (v >= 0 && xIn2 - wH < plotL + 2) {
                  valueLabels.push('<text x="' + (plotR - 2).toFixed(1) + '" y="' + cyH.toFixed(1)
                    + '" text-anchor="end" font-size="' + labFsH + '" fill="' + valueColor + '">' + esc(labH) + '</text>');
                } else {
                  valueLabels.push('<text x="' + xIn2.toFixed(1) + '" y="' + cyH.toFixed(1) + '" text-anchor="'
                    + (v >= 0 ? 'end' : 'start') + '" font-weight="600" font-size="' + labFsH
                    + '" fill="#ffffff">' + esc(labH) + '</text>');
                }
              }
            }
          } else {
            var xx = plotL + slot * i + (slot - bandW) / 2 + (stacked ? 0 : off);
            var ww = stacked ? bandW : (useGrouped ? groupW * 0.92 : bandW);
            var y1v = v >= 0 ? start - len : start;
            var yTop = stacked ? start - len - offsetStack : start - len;
            parts.push('<rect x="' + xx.toFixed(1) + '" y="' + (stacked ? yTop : y1v).toFixed(1) + '" width="'
              + Math.max(1, ww).toFixed(1) + '" height="' + Math.max(0, len).toFixed(1) + '" rx="'
              + Math.min(barRadius, ww / 2).toFixed(1) + '" fill="' + col + '"/>');
            if (showValues && len > 0) {
              var labV = valText(v);
              var labFsV = Math.max(8, Math.min(slotFs - 1, Math.round((useGrouped && !stacked ? groupW : ww) / 2.2)));
              var wV = estTextWidth(labV, labFsV);
              var labelY = (stacked ? yTop : y1v) - 5;
              if (eb) labelY = plotB - axisValue(clamp(v + eb.half, yMin, yMax)) * plotH - 5;
              // 分组柱：标签比柱体宽时按系列号上下错开一排，避免相邻系列标签横向相撞
              if (useGrouped && !stacked && seriesCount > 1 && wV > groupW - 2) {
                labelY -= (si % 2) * (labFsV + 3);
              }
              labelY = Math.max(labelY, plotT + labFsV);
              valueLabels.push('<text x="' + (xx + ww / 2).toFixed(1) + '" y="' + labelY.toFixed(1)
                + '" text-anchor="middle" font-size="' + labFsV + '" fill="' + valueColor + '">'
                + esc(labV) + '</text>');
            }
          }
        });
      });
      if (errBars.length && !stacked) {
        errBars.forEach(function (b) { parts.push(errorBarSvg(b.i, b.v, b.half)); });
      }
      if (valueLabels.length) parts.push(valueLabels.join(''));
      return open + head + parts.join('') + legendSvg() + sigSvgMarkup + '</svg>';
    }

    // ---- 折线 / 面积（含堆叠面积）
    var lineKinds = { line: 1, area: 1, stackedArea: 1, scatter: 1, bubble: 1 };
    if (lineKinds[kind]) {
      function xAt(idx) {
        if (!isXY) return plotL + slot * idx + slot / 2;
        var span = (xMax - xMin) || 1;
        return plotL + plotW * (xVals[idx] - xMin) / span;
      }
      function yAt(v) {
        return plotB - axisValue(v) * plotH;
      }
      var bandFs = slotFs;
      var stackAcc2 = d.labels.map(function () { return 0; });
      // 折线 / 面积的数值标签也先收集，等误差棒画完再叠上去（同理避免被误差棒竖线压住）
      var lineLabels = [];
      d.values.forEach(function (arr, si) {
        var col = pickColor(colors, kind === 'scatter' || kind === 'bubble' ? si : si);
        var pts = [];
        arr.forEach(function (v, i) {
          var yv = v;
          if (kind === 'stackedArea') {
            stackAcc2[i] += v;
            yv = stackAcc2[i];
          }
          pts.push([xAt(i), yAt(yv)]);
        });
        if (kind === 'area' || kind === 'stackedArea') {
          var areaPts = pts.slice();
          areaPts.push([pts[pts.length - 1][0], plotB]);
          areaPts.push([pts[0][0], plotB]);
          parts.push('<polygon points="' + areaPts.map(function (q) { return q[0].toFixed(1) + ',' + q[1].toFixed(1); }).join(' ')
            + '" fill="' + col + '" fill-opacity="' + areaOpacity + '"/>');
        }
        if (!isXY) {
          parts.push('<path d="' + (p.smooth ? smoothPath(pts) : 'M' + pts.map(function (q) {
            return q[0].toFixed(1) + ' ' + q[1].toFixed(1);
          }).join(' L')) + '" fill="none" stroke="' + col + '" stroke-width="' + lineWidth
            + '" stroke-linejoin="round" stroke-linecap="round"/>');
        }
        if (showPoints || isXY) {
          pts.forEach(function (q, i) {
            var rad = isXY
              ? (kind === 'bubble' ? clamp(Math.sqrt(sizeAt(i)) * 2.4, 3, 28) : 4)
              : 3.6;
            parts.push('<circle cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="' + rad
              + '" fill="' + (isXY ? col : '#ffffff') + '" fill-opacity="' + (isXY ? 0.72 : 1)
              + '" stroke="' + col + '" stroke-width="' + (isXY ? 1.2 : 2) + '"/>');
            if (showValues && !isXY) {
              var labL = valText(arr[i]);
              var ftL = estTextWidth(labL, bandFs) > slot - 2
                ? fitLabel(labL, 2 * slot - 4, bandFs, 3) : { text: labL, fs: bandFs };
              // 相邻点太密时隔点上抬一行，避免数值标签横向相撞
              var stL = ftL.text === labL && estTextWidth(labL, ftL.fs) > slot - 2
                ? (i % 2) * (ftL.fs + 3) : 0;
              var ly = q[1] - 9 - stL;
              var eb2 = stacked ? null : ebByIndex[i];
              if (eb2) ly = plotB - axisValue(clamp(arr[i] + eb2.half, yMin, yMax)) * plotH - 9 - stL;
              ly = Math.max(ly, plotT + ftL.fs);
              lineLabels.push('<text x="' + q[0].toFixed(1) + '" y="' + ly.toFixed(1)
                + '" text-anchor="middle" font-size="' + ftL.fs + '" fill="' + valueColor + '">'
                + esc(ftL.text) + '</text>');
            }
          });
        }
      });
      if (errBars.length && !isXY && !stacked) {
        errBars.forEach(function (b) { parts.push(errorBarSvg(b.i, b.v, b.half)); });
      }
      // ---- 拟合线（散点 / 气泡用数值 x，折线 / 面积用类目索引 x）
      if (FIT_KINDS[kind] === 1 && fitType !== 'none') {
        var fxAt = function (x) {
          if (isXY) return plotL + plotW * (x - xMin) / ((xMax - xMin) || 1);
          return plotL + slot * x + slot / 2;
        };
        d.values.forEach(function (arr, si) {
          var xs2 = [];
          var ys2 = [];
          arr.forEach(function (v, i) { xs2.push(isXY ? xVals[i] : i); ys2.push(v); });
          var fs2 = fitSummary(xs2, ys2, fitType);
          if (!fs2) return;
          var lo2 = isXY ? xMin : 0;
          var hi2 = isXY ? xMax : Math.max(1, nCat - 1);
          var dpath = '';
          for (var t2 = 0; t2 <= 48; t2 += 1) {
            var xv2 = lo2 + (hi2 - lo2) * t2 / 48;
            dpath += (t2 ? ' L' : 'M') + fxAt(xv2).toFixed(1) + ' ' + yAt(clamp(fs2.fn(xv2), yMin, yMax)).toFixed(1);
          }
          parts.push('<path d="' + dpath + '" fill="none" stroke="' + fitColor + '" stroke-width="' + fitWidth
            + '" stroke-dasharray="6 4" stroke-linecap="round"/>');
          var lab = fitShowEq ? fs2.eq : '';
          if (fitShowR2) lab += (lab ? '   ' : '') + 'R² = ' + fs2.r2.toFixed(3);
          if (lab) {
            // 加一层半透明白底衬，拟合方程压在散点上时也能读清
            var ffs = Math.max(9, tickFs - 1);
            var fw = Math.min(estTextWidth(lab, ffs) + 8, plotW - 8);
            var fy = plotT + 14 + si * 14;
            parts.push('<rect x="' + (plotL + 4).toFixed(1) + '" y="' + (fy - 12).toFixed(1) + '" width="'
              + fw.toFixed(1) + '" height="14" rx="2" fill="#ffffff" fill-opacity="0.85"/>');
            parts.push('<text x="' + (plotL + 8).toFixed(1) + '" y="' + fy.toFixed(1)
              + '" font-size="' + ffs + '" fill="' + fitColor + '">' + esc(lab) + '</text>');
          }
        });
      }
      if (lineLabels.length) parts.push(lineLabels.join(''));
      return open + head + parts.join('') + legendSvg() + sigSvgMarkup + '</svg>';
    }

    // ---- 未识别类型：退回柱状图，避免整块空白
    return chartSvg(Object.assign({}, p, { kind: 'bar' }));
  }

  ACRender.chartSvg = chartSvg;
  ACRender.CHART_PALETTE = CHART_PALETTE;

  // ---------------------------------------------------------------- 形状（Shape）
  /* 形状统一走 SVG 矢量：一份几何同时服务画布 / 缩略图 / HTML 导出 / PPTX 栅格。
   * 命名对齐 PowerPoint 的 OOXML 预设几何名（a:prstGeom@prst），导出可 1:1 对应。
   * 每个几何体是 SHAPE_GEOMS 里的一条：function (W, H, props) → { d, detail, rule }
   *   d      主轮廓（填充 + 描边）；多个闭合子路径配合 evenodd 做镂空（donut / frame）
   *   detail 只描边的附加线（can / cube 的内壁等），可为空
   *   rule   填充规则，默认 evenodd
   * 填充色沿用 style.background，描边沿用 style.borderWidth / borderColor，
   * 圆角沿用 style.borderRadius（分角见 props.radiusTL / TR / BR / BL）。 */

  var SHAPE_NAMES = [
    'rect', 'roundRect', 'round1Rect', 'round2SameRect', 'round2DiagRect',
    'snip1Rect', 'snip2SameRect', 'snip2DiagRect', 'snipRoundRect',
    'ellipse', 'triangle', 'rtTriangle', 'diamond', 'parallelogram',
    'trapezoid', 'nonIsoscelesTrapezoid',
    'pentagon', 'hexagon', 'heptagon', 'octagon', 'decagon', 'dodecagon',
    'plaque', 'can', 'cube', 'bevel', 'donut', 'blockArc', 'pie', 'pieWedge', 'chord',
    'teardrop', 'frame', 'halfFrame', 'corner', 'diagStripe',
    'moon', 'sun', 'cloud', 'heart', 'lightningBolt', 'smileyFace', 'noSmoking', 'arc',
    'star4', 'star5', 'star6', 'star7', 'star8', 'star10', 'star12', 'star16', 'star24', 'star32',
    'rightArrow', 'leftArrow', 'upArrow', 'downArrow', 'leftRightArrow', 'upDownArrow',
    'quadArrow', 'leftRightUpArrow', 'bentArrow', 'uturnArrow', 'leftUpArrow',
    'notchedRightArrow', 'chevron', 'homePlate',
    'flowChartProcess', 'flowChartDecision', 'flowChartTerminator', 'flowChartDocument',
    'flowChartPredefinedProcess', 'flowChartInternalStorage', 'flowChartConnector',
    'flowChartSort', 'flowChartExtract', 'flowChartMerge', 'flowChartMagneticDisk',
    'flowChartOffpageConnector', 'wedgeRectCallout', 'cloudCallout',
    'cross', 'mathPlus', 'flag', 'line'
  ];

  var SHAPE_LABELS = {
    rect: '矩形', roundRect: '圆角矩形', round1Rect: '单圆角矩形', round2SameRect: '同侧双圆角矩形',
    round2DiagRect: '对角双圆角矩形', snip1Rect: '单切角矩形', snip2SameRect: '同侧双切角矩形',
    snip2DiagRect: '对角双切角矩形', snipRoundRect: '切角圆角矩形',
    ellipse: '椭圆', triangle: '等腰三角形', rtTriangle: '直角三角形', diamond: '菱形',
    parallelogram: '平行四边形', trapezoid: '梯形', nonIsoscelesTrapezoid: '不等腰梯形',
    pentagon: '五边形', hexagon: '六边形', heptagon: '七边形', octagon: '八边形',
    decagon: '十边形', dodecagon: '十二边形', plaque: '铭牌', can: '圆柱', cube: '立方体',
    bevel: '斜切', donut: '圆环', blockArc: '环形块', pie: '饼形', pieWedge: '饼形楔',
    chord: '弓形', teardrop: '泪滴', frame: '画框', halfFrame: '半画框', corner: '角形',
    diagStripe: '斜条纹', moon: '月牙', sun: '太阳', cloud: '云', heart: '心形',
    lightningBolt: '闪电', smileyFace: '笑脸', noSmoking: '禁止标志', arc: '弧形',
    star4: '四角星', star5: '五角星', star6: '六角星', star7: '七角星', star8: '八角星',
    star10: '十角星', star12: '十二角星', star16: '十六角星', star24: '二十四角星', star32: '三十二角星',
    rightArrow: '右箭头', leftArrow: '左箭头', upArrow: '上箭头', downArrow: '下箭头',
    leftRightArrow: '左右箭头', upDownArrow: '上下箭头', quadArrow: '四向箭头',
    leftRightUpArrow: '左右上箭头', bentArrow: '折弯箭头', uturnArrow: '回转箭头',
    leftUpArrow: '左上箭头', notchedRightArrow: '燕尾右箭头', chevron: '箭头条', homePlate: '五边形箭头',
    flowChartProcess: '流程-处理', flowChartDecision: '流程-判断', flowChartTerminator: '流程-起止',
    flowChartDocument: '流程-文档', flowChartPredefinedProcess: '流程-预定义',
    flowChartInternalStorage: '流程-内存储', flowChartConnector: '流程-连接符',
    flowChartSort: '流程-排序', flowChartExtract: '流程-提取', flowChartMerge: '流程-合并',
    flowChartMagneticDisk: '流程-磁盘', flowChartOffpageConnector: '流程-离页',
    wedgeRectCallout: '矩形标注', cloudCallout: '云形标注',
    cross: '十字', mathPlus: '加号', flag: '旗帜', line: '直线'
  };

  // ↓↓↓ 形状几何库（几何实现统一写在这一块，勿它处重复声明 SHAPE_GEOMS） ↓↓↓
  // ---- 几何辅助 ----
  function gnum(v) { return Math.round(v * 10) / 10; }
  function gpts(pts, close) {
    var s = '';
    for (var i = 0; i < pts.length; i += 1) s += (i ? 'L' : 'M') + gnum(pts[i][0]) + ' ' + gnum(pts[i][1]);
    return close === false ? s : s + 'Z';
  }
  /** 椭圆上按角度取点：0° 在右，顺时针为正（屏幕坐标 y 向下）。 */
  function gpt(cx, cy, rx, ry, deg) {
    var a = deg * Math.PI / 180;
    return [cx + rx * Math.cos(a), cy + ry * Math.sin(a)];
  }
  function gell(cx, cy, rx, ry) {
    return 'M' + gnum(cx - rx) + ' ' + gnum(cy)
      + 'A' + gnum(rx) + ' ' + gnum(ry) + ' 0 1 0 ' + gnum(cx + rx) + ' ' + gnum(cy)
      + 'A' + gnum(rx) + ' ' + gnum(ry) + ' 0 1 0 ' + gnum(cx - rx) + ' ' + gnum(cy) + 'Z';
  }
  /** 开放弧线（只描边用）。 */
  function garc(cx, cy, rx, ry, a0, a1) {
    var p0 = gpt(cx, cy, rx, ry, a0);
    var p1 = gpt(cx, cy, rx, ry, a1);
    return 'M' + gnum(p0[0]) + ' ' + gnum(p0[1]) + 'A' + gnum(rx) + ' ' + gnum(ry) + ' 0 '
      + (Math.abs(a1 - a0) > 180 ? 1 : 0) + ' 1 ' + gnum(p1[0]) + ' ' + gnum(p1[1]);
  }
  /** 扇形（圆心 → 起弧 → 扫到终点 → 闭合）。 */
  function gsector(cx, cy, rx, ry, a0, a1) {
    var p0 = gpt(cx, cy, rx, ry, a0);
    var p1 = gpt(cx, cy, rx, ry, a1);
    return 'M' + gnum(cx) + ' ' + gnum(cy) + 'L' + gnum(p0[0]) + ' ' + gnum(p0[1]) + 'A'
      + gnum(rx) + ' ' + gnum(ry) + ' 0 ' + (Math.abs(a1 - a0) > 180 ? 1 : 0) + ' 1 '
      + gnum(p1[0]) + ' ' + gnum(p1[1]) + 'Z';
  }
  /** n 角星：rot 起始角（弧度），rx/ry 外接椭圆半径，ratio 内外半径比。 */
  function gstar(cx, cy, rx, ry, n, rot, ratio) {
    var pts = [];
    for (var i = 0; i < n * 2; i += 1) {
      var k = i % 2 ? ratio : 1;
      var a = rot + i * Math.PI / n;
      pts.push([cx + rx * k * Math.cos(a), cy + ry * k * Math.sin(a)]);
    }
    return gpts(pts);
  }
  /** 占满 W×H 外接椭圆的内接正多边形（rot 起始角，弧度）。 */
  function gpoly(W, H, n, rot) {
    var pts = [];
    for (var i = 0; i < n; i += 1) {
      var a = rot + i * 2 * Math.PI / n;
      pts.push([W / 2 + W / 2 * Math.cos(a), H / 2 + H / 2 * Math.sin(a)]);
    }
    return gpts(pts);
  }
  /** 四角圆角矩形（角半径各自独立，0 表示直角）。 */
  function grrect(W, H, tl, tr, br, bl) {
    var m = Math.min(W, H) / 2;
    tl = Math.max(0, Math.min(tl, m)); tr = Math.max(0, Math.min(tr, m));
    br = Math.max(0, Math.min(br, m)); bl = Math.max(0, Math.min(bl, m));
    var d = 'M' + gnum(tl) + ' 0L' + gnum(W - tr) + ' 0';
    if (tr) d += 'A' + gnum(tr) + ' ' + gnum(tr) + ' 0 0 1 ' + gnum(W) + ' ' + gnum(tr);
    d += 'L' + gnum(W) + ' ' + gnum(H - br);
    if (br) d += 'A' + gnum(br) + ' ' + gnum(br) + ' 0 0 1 ' + gnum(W - br) + ' ' + gnum(H);
    d += 'L' + gnum(bl) + ' ' + gnum(H);
    if (bl) d += 'A' + gnum(bl) + ' ' + gnum(bl) + ' 0 0 1 0 ' + gnum(H - bl);
    d += 'L0 ' + gnum(tl);
    if (tl) d += 'A' + gnum(tl) + ' ' + gnum(tl) + ' 0 0 1 ' + gnum(tl) + ' 0';
    return d + 'Z';
  }
  /** 四角切角矩形。 */
  function gsrect(W, H, tl, tr, br, bl) {
    return gpts([[tl, 0], [W - tr, 0], [W, tr], [W, H - br], [W - br, H], [bl, H], [0, H - bl], [0, tl]]);
  }
  function gnumOr(v, d) {
    var n = Number(v);
    return isFinite(n) ? n : d;
  }
  /**
   * 取四角圆角半径，顺序 左上/右上/右下/左下。
   * 优先级：逐角 props.radiusTL/TR/BR/BL > 统一 style.borderRadius(>0) > 形状自带比例 dflt。
   * 空串 / null / undefined 视为「未设」；统一圆角为 0 也视为「未设」，交给形状比例
   * （否则圆角矩形会被 0 抹平成直角，见 element-schema.json 里 borderRadius 的默认值）。
   */
  function gcorners(p, st, dflt) {
    p = p || {};
    var uni = gnumOr(st && st.borderRadius, 0);
    function pick(key, d) {
      var v = p[key];
      if (v !== '' && v !== null && v !== undefined) {
        var n = Number(v);
        if (isFinite(n)) return Math.max(0, n);
      }
      return uni > 0 ? uni : Math.max(0, d);
    }
    return [pick('radiusTL', dflt[0]), pick('radiusTR', dflt[1]), pick('radiusBR', dflt[2]), pick('radiusBL', dflt[3])];
  }

  var SHAPE_GEOMS = {
    rect: function (W, H, p, st) {
      var c = gcorners(p, st, [0, 0, 0, 0]);
      if (!c[0] && !c[1] && !c[2] && !c[3]) return { d: gpts([[0, 0], [W, 0], [W, H], [0, H]]) };
      return { d: grrect(W, H, c[0], c[1], c[2], c[3]) };
    },
    // 圆角矩形族：默认圆角按短边比例，统一圆角 / 逐角半径都能覆盖（这就是改弧度的入口）。
    roundRect: function (W, H, p, st) {
      var k = Math.min(W, H) * 0.16667;
      var c = gcorners(p, st, [k, k, k, k]);
      return { d: grrect(W, H, c[0], c[1], c[2], c[3]) };
    },
    round1Rect: function (W, H, p, st) {
      var k = Math.min(W, H) * 0.16667;
      var c = gcorners(p, st, [k, 0, 0, 0]);
      return { d: grrect(W, H, c[0], c[1], c[2], c[3]) };
    },
    round2SameRect: function (W, H, p, st) {
      var k = Math.min(W, H) * 0.16667;
      var c = gcorners(p, st, [k, k, 0, 0]);
      return { d: grrect(W, H, c[0], c[1], c[2], c[3]) };
    },
    round2DiagRect: function (W, H, p, st) {
      var k = Math.min(W, H) * 0.16667;
      var c = gcorners(p, st, [k, 0, k, 0]);
      return { d: grrect(W, H, c[0], c[1], c[2], c[3]) };
    },
    snip1Rect: function (W, H) { var s = Math.min(W, H) * 0.25; return { d: gsrect(W, H, s, 0, 0, 0) }; },
    snip2SameRect: function (W, H) { var s = Math.min(W, H) * 0.25; return { d: gsrect(W, H, s, s, 0, 0) }; },
    snip2DiagRect: function (W, H) { var s = Math.min(W, H) * 0.25; return { d: gsrect(W, H, s, 0, s, 0) }; },
    snipRoundRect: function (W, H) {
      var r = Math.min(W, H) * 0.16667;
      var s = Math.min(W, H) * 0.25;
      return { d: 'M' + gnum(r) + ' 0L' + gnum(W - s) + ' 0L' + gnum(W) + ' ' + gnum(s)
        + 'L' + gnum(W) + ' ' + gnum(H - s) + 'L' + gnum(W - s) + ' ' + gnum(H)
        + 'L' + gnum(s) + ' ' + gnum(H) + 'L0 ' + gnum(H - s) + 'L0 ' + gnum(r)
        + 'A' + gnum(r) + ' ' + gnum(r) + ' 0 0 1 ' + gnum(r) + ' 0Z' };
    },
    ellipse: function (W, H) { return { d: gell(W / 2, H / 2, W / 2, H / 2) }; },
    triangle: function (W, H) { return { d: gpts([[W / 2, 0], [W, H], [0, H]]) }; },
    rtTriangle: function (W, H) { return { d: gpts([[0, 0], [0, H], [W, H]]) }; },
    diamond: function (W, H) { return { d: gpts([[W / 2, 0], [W, H / 2], [W / 2, H], [0, H / 2]]) }; },
    parallelogram: function (W, H) { var k = W * 0.25; return { d: gpts([[k, 0], [W, 0], [W - k, H], [0, H]]) }; },
    trapezoid: function (W, H) { var k = W * 0.25; return { d: gpts([[k, 0], [W - k, 0], [W, H], [0, H]]) }; },
    nonIsoscelesTrapezoid: function (W, H) { var k = W * 0.25; return { d: gpts([[0, 0], [W - k, 0], [W, H], [0, H]]) }; },
    pentagon: function (W, H) { return { d: gpoly(W, H, 5, -Math.PI / 2) }; },
    hexagon: function (W, H) { return { d: gpoly(W, H, 6, 0) }; },
    heptagon: function (W, H) { return { d: gpoly(W, H, 7, -Math.PI / 2) }; },
    octagon: function (W, H) { return { d: gpoly(W, H, 8, -Math.PI / 2) }; },
    decagon: function (W, H) { return { d: gpoly(W, H, 10, -Math.PI / 2) }; },
    dodecagon: function (W, H) { return { d: gpoly(W, H, 12, -Math.PI / 2) }; },
    bevel: function (W, H) { var k = Math.min(W, H) * 0.25; return { d: gsrect(W, H, k, k, k, k) }; },
    plaque: function (W, H) { var r = Math.min(W, H) * 0.25; return { d: grrect(W, H, r, r, r, r) }; },
    cross: function (W, H) {
      var tx = W * 0.16, ty = H * 0.16;
      var a = W / 2 - tx, b = W / 2 + tx, c = H / 2 - ty, e = H / 2 + ty;
      return { d: gpts([[a, 0], [b, 0], [b, c], [W, c], [W, e], [b, e], [b, H], [a, H], [a, e], [0, e], [0, c], [a, c]]) };
    },
    mathPlus: function (W, H) {
      var tx = W * 0.09, ty = H * 0.09;
      var a = W / 2 - tx, b = W / 2 + tx, c = H / 2 - ty, e = H / 2 + ty;
      return { d: gpts([[a, 0], [b, 0], [b, c], [W, c], [W, e], [b, e], [b, H], [a, H], [a, e], [0, e], [0, c], [a, c]]) };
    },
    frame: function (W, H) {
      var k = Math.min(W, H) * 0.25;
      return { d: gpts([[0, 0], [W, 0], [W, H], [0, H]]) + gpts([[k, k], [W - k, k], [W - k, H - k], [k, H - k]]) };
    },
    halfFrame: function (W, H) {
      var k = Math.min(W, H) * 0.3;
      return { d: gpts([[0, 0], [W, 0], [W, k], [k, k], [k, H], [0, H]]) };
    },
    corner: function (W, H) {
      var k = Math.min(W, H) * 0.35;
      return { d: gpts([[W, 0], [W, k], [k, k], [k, H], [0, H], [0, 0]]) };
    },
    diagStripe: function (W, H) {
      var k = Math.min(W, H) * 0.3;
      return { d: gpts([[0, H], [0, H - k], [W - k, 0], [W, 0], [W, k], [k, H]]) };
    },
    donut: function (W, H) {
      return { d: gell(W / 2, H / 2, W / 2, H / 2) + gell(W / 2, H / 2, W * 0.3, H * 0.3) };
    },
    can: function (W, H) {
      var rx = W / 2, ry = Math.min(W, H) * 0.15;
      return { d: 'M0 ' + gnum(ry) + 'A' + gnum(rx) + ' ' + gnum(ry) + ' 0 0 1 ' + gnum(W) + ' ' + gnum(ry)
        + 'L' + gnum(W) + ' ' + gnum(H - ry) + 'A' + gnum(rx) + ' ' + gnum(ry) + ' 0 0 1 0 ' + gnum(H - ry) + 'Z',
        detail: gell(rx, ry, rx, ry) };
    },
    cube: function (W, H) {
      var k = Math.min(W, H) * 0.25;
      return { d: gpts([[0, k], [W - k, k], [W - k, H], [0, H]]),
        detail: 'M0 ' + gnum(k) + 'L' + gnum(k) + ' 0L' + gnum(W) + ' 0L' + gnum(W - k) + ' ' + gnum(k)
          + 'M' + gnum(W) + ' 0L' + gnum(W) + ' ' + gnum(H - k) + 'L' + gnum(W - k) + ' ' + gnum(H) };
    },
    teardrop: function (W, H) {
      var cx = W / 2, cy = H / 2, rx = W / 2, ry = H / 2;
      return { d: 'M' + gnum(W) + ' 0Q' + gnum(cx + rx * 0.15) + ' ' + gnum(cy - ry * 0.95) + ' ' + gnum(cx) + ' ' + gnum(cy - ry)
        + 'A' + gnum(rx) + ' ' + gnum(ry) + ' 0 1 1 ' + gnum(cx + rx) + ' ' + gnum(cy)
        + 'Q' + gnum(cx + rx * 0.95) + ' ' + gnum(cy - ry * 0.15) + ' ' + gnum(W) + ' 0Z' };
    },
    blockArc: function (W, H) {
      var cx = W / 2, cy = H / 2, rx = W / 2, ry = H / 2;
      var irx = rx * 0.6, iry = ry * 0.6;
      var p0 = gpt(cx, cy, rx, ry, -90), p1 = gpt(cx, cy, rx, ry, 180);
      var q0 = gpt(cx, cy, irx, iry, 180), q1 = gpt(cx, cy, irx, iry, -90);
      return { d: 'M' + gnum(p0[0]) + ' ' + gnum(p0[1])
        + 'A' + gnum(rx) + ' ' + gnum(ry) + ' 0 1 1 ' + gnum(p1[0]) + ' ' + gnum(p1[1])
        + 'L' + gnum(q0[0]) + ' ' + gnum(q0[1])
        + 'A' + gnum(irx) + ' ' + gnum(iry) + ' 0 1 0 ' + gnum(q1[0]) + ' ' + gnum(q1[1]) + 'Z' };
    },
    pie: function (W, H) { return { d: gsector(W / 2, H / 2, W / 2, H / 2, -90, 180) }; },
    pieWedge: function (W, H) { return { d: gsector(W / 2, H / 2, W / 2, H / 2, 0, 90) }; },
    chord: function (W, H) {
      var cx = W / 2, cy = H / 2, rx = W / 2, ry = H / 2;
      var p0 = gpt(cx, cy, rx, ry, -60), p1 = gpt(cx, cy, rx, ry, 60);
      return { d: 'M' + gnum(p0[0]) + ' ' + gnum(p0[1]) + 'A' + gnum(rx) + ' ' + gnum(ry) + ' 0 1 1 '
        + gnum(p1[0]) + ' ' + gnum(p1[1]) + 'Z' };
    },
    moon: function (W, H) {
      var cx = W / 2, cy = H / 2, rx = W / 2, ry = H / 2;
      return { d: gell(cx, cy, rx, ry) + gell(cx + W * 0.28, cy, rx * 0.9, ry * 0.9) };
    },
    arc: function (W, H) { return { d: '', detail: garc(W / 2, H / 2, W / 2, H / 2, 180, 0) }; },
    sun: function (W, H) {
      var cx = W / 2, cy = H / 2;
      var R = Math.min(W, H) / 2, r = R * 0.58;
      var lines = '';
      for (var i = 0; i < 12; i += 1) {
        var p0 = gpt(cx, cy, r, r, i * 30), p1 = gpt(cx, cy, R, R, i * 30);
        lines += 'M' + gnum(p0[0]) + ' ' + gnum(p0[1]) + 'L' + gnum(p1[0]) + ' ' + gnum(p1[1]);
      }
      return { d: gell(cx, cy, r, r), detail: lines };
    },
    cloud: function (W, H) {
      return { d: 'M' + gnum(W * 0.18) + ' ' + gnum(H * 0.85)
        + 'C' + gnum(W * 0.02) + ' ' + gnum(H * 0.85) + ' ' + gnum(W * 0.02) + ' ' + gnum(H * 0.6)
        + ' ' + gnum(W * 0.16) + ' ' + gnum(H * 0.57)
        + 'C' + gnum(W * 0.11) + ' ' + gnum(H * 0.3) + ' ' + gnum(W * 0.34) + ' ' + gnum(H * 0.24)
        + ' ' + gnum(W * 0.44) + ' ' + gnum(H * 0.36)
        + 'C' + gnum(W * 0.52) + ' ' + gnum(H * 0.13) + ' ' + gnum(W * 0.79) + ' ' + gnum(H * 0.15)
        + ' ' + gnum(W * 0.8) + ' ' + gnum(H * 0.4)
        + 'C' + gnum(W * 1.0) + ' ' + gnum(H * 0.4) + ' ' + gnum(W * 1.02) + ' ' + gnum(H * 0.85)
        + ' ' + gnum(W * 0.86) + ' ' + gnum(H * 0.85) + 'Z' };
    },
    heart: function (W, H) {
      return { d: 'M' + gnum(W / 2) + ' ' + gnum(H * 0.95)
        + 'C' + gnum(-W * 0.1) + ' ' + gnum(H * 0.55) + ' ' + gnum(W * 0.12) + ' ' + gnum(H * 0.05)
        + ' ' + gnum(W / 2) + ' ' + gnum(H * 0.28)
        + 'C' + gnum(W * 0.88) + ' ' + gnum(H * 0.05) + ' ' + gnum(W * 1.1) + ' ' + gnum(H * 0.55)
        + ' ' + gnum(W / 2) + ' ' + gnum(H * 0.95) + 'Z' };
    },
    lightningBolt: function (W, H) {
      return { d: gpts([[W * 0.42, 0], [W * 0.78, 0], [W * 0.5, H * 0.44], [W * 0.78, H * 0.44],
        [W * 0.3, H], [W * 0.44, H * 0.56], [W * 0.18, H * 0.56]]) };
    },
    smileyFace: function (W, H) {
      var cx = W / 2, cy = H / 2, rx = W / 2, ry = H / 2;
      var eyes = gell(cx - W * 0.18, cy - H * 0.16, W * 0.07, H * 0.1)
        + gell(cx + W * 0.18, cy - H * 0.16, W * 0.07, H * 0.1);
      return { d: gell(cx, cy, rx, ry) + eyes, detail: garc(cx, cy, rx * 0.62, ry * 0.62, 25, 155) };
    },
    noSmoking: function (W, H) {
      var cx = W / 2, cy = H / 2, k = Math.min(W, H) * 0.36;
      return { d: gell(cx, cy, W / 2, H / 2),
        detail: 'M' + gnum(cx - k) + ' ' + gnum(cy + k) + 'L' + gnum(cx + k) + ' ' + gnum(cy - k) };
    },
    // 直线：与 OOXML 预设几何 line 一致 —— 左上角连到右下角（即包围盒的对角线）。
    // 旧版画的是水平中线，(2×210) 这类竖直细线会缩成中点上的一个点，
    // 画布上的竖排分隔线 / 管路正是这种细长条，于是整条线消失。
    line: function (W, H) { return { d: '', detail: 'M0 0L' + gnum(W) + ' ' + gnum(H) }; },
    star4: function (W, H) { return { d: gstar(W / 2, H / 2, W / 2, H / 2, 4, -Math.PI / 2, 0.38) }; },
    star5: function (W, H) { return { d: gstar(W / 2, H / 2, W / 2, H / 2, 5, -Math.PI / 2, 0.382) }; },
    star6: function (W, H) { return { d: gstar(W / 2, H / 2, W / 2, H / 2, 6, -Math.PI / 2, 0.5) }; },
    star7: function (W, H) { return { d: gstar(W / 2, H / 2, W / 2, H / 2, 7, -Math.PI / 2, 0.55) }; },
    star8: function (W, H) { return { d: gstar(W / 2, H / 2, W / 2, H / 2, 8, -Math.PI / 2, 0.55) }; },
    star10: function (W, H) { return { d: gstar(W / 2, H / 2, W / 2, H / 2, 10, -Math.PI / 2, 0.62) }; },
    star12: function (W, H) { return { d: gstar(W / 2, H / 2, W / 2, H / 2, 12, -Math.PI / 2, 0.68) }; },
    star16: function (W, H) { return { d: gstar(W / 2, H / 2, W / 2, H / 2, 16, -Math.PI / 2, 0.75) }; },
    star24: function (W, H) { return { d: gstar(W / 2, H / 2, W / 2, H / 2, 24, -Math.PI / 2, 0.82) }; },
    star32: function (W, H) { return { d: gstar(W / 2, H / 2, W / 2, H / 2, 32, -Math.PI / 2, 0.87) }; },
    rightArrow: function (W, H) {
      return { d: gpts([[0, H * 0.25], [W * 0.6, H * 0.25], [W * 0.6, 0], [W, H / 2],
        [W * 0.6, H], [W * 0.6, H * 0.75], [0, H * 0.75]]) };
    },
    leftArrow: function (W, H) {
      return { d: gpts([[0, H / 2], [W * 0.4, 0], [W * 0.4, H * 0.25], [W, H * 0.25],
        [W, H * 0.75], [W * 0.4, H * 0.75], [W * 0.4, H]]) };
    },
    upArrow: function (W, H) {
      return { d: gpts([[W / 2, 0], [W, H * 0.4], [W * 0.75, H * 0.4], [W * 0.75, H],
        [W * 0.25, H], [W * 0.25, H * 0.4], [0, H * 0.4]]) };
    },
    downArrow: function (W, H) {
      return { d: gpts([[W / 2, H], [0, H * 0.6], [W * 0.25, H * 0.6], [W * 0.25, 0],
        [W * 0.75, 0], [W * 0.75, H * 0.6], [W, H * 0.6]]) };
    },
    leftRightArrow: function (W, H) {
      return { d: gpts([[0, H / 2], [W * 0.3, 0], [W * 0.3, H * 0.25], [W * 0.7, H * 0.25],
        [W * 0.7, 0], [W, H / 2], [W * 0.7, H], [W * 0.7, H * 0.75], [W * 0.3, H * 0.75], [W * 0.3, H]]) };
    },
    upDownArrow: function (W, H) {
      return { d: gpts([[W / 2, 0], [W, H * 0.3], [W * 0.75, H * 0.3], [W * 0.75, H * 0.7],
        [W, H * 0.7], [W / 2, H], [W * 0.25, H * 0.7], [W * 0.25, H * 0.3], [0, H * 0.3]]) };
    },
    quadArrow: function (W, H) {
      var m = Math.min(W, H);
      var hw = m * 0.18, hl = m * 0.28, sh = m * 0.09;
      var mx = W / 2, my = H / 2;
      return { d: gpts([
        [mx, 0], [mx + hw, hl], [mx + sh, hl], [mx + sh, my - sh],
        [W - hl, my - sh], [W - hl, my - hw], [W, my], [W - hl, my + hw], [W - hl, my + sh],
        [mx + sh, my + sh], [mx + sh, H - hl], [mx + hw, H - hl], [mx, H], [mx - hw, H - hl],
        [mx - sh, H - hl], [mx - sh, my + sh], [hl, my + sh], [hl, my + hw], [0, my],
        [hl, my - hw], [hl, my - sh], [mx - sh, my - sh], [mx - sh, hl], [mx - hw, hl]]) };
    },
    leftRightUpArrow: function (W, H) {
      var m = Math.min(W, H);
      var hw = m * 0.18, hl = m * 0.28, sh = m * 0.09;
      var mx = W / 2, my = H / 2;
      return { d: gpts([
        [mx, 0], [mx + hw, hl], [mx + sh, hl], [mx + sh, my - sh],
        [W, my - sh], [W, my + sh], [mx + sh, my + sh], [mx + sh, H], [mx - sh, H],
        [mx - sh, my + sh], [hl, my + sh], [hl, my + hw], [0, my], [hl, my - hw],
        [hl, my - sh], [mx - sh, my - sh], [mx - sh, hl], [mx - hw, hl]]) };
    },
    bentArrow: function (W, H) {
      var m = Math.min(W, H);
      var sh = m * 0.14, hw = m * 0.2, hl = m * 0.24;
      var cx = W - hw;
      return { d: gpts([
        [0, H], [0, H - 2 * sh], [cx + sh, H - 2 * sh], [cx + sh, hl], [W, hl],
        [cx, 0], [cx - hw, hl], [cx - sh, hl], [cx - sh, H]]) };
    },
    uturnArrow: function (W, H) {
      var m = Math.min(W, H);
      var sh = m * 0.14, hl = m * 0.24;
      var a = 2 * sh;
      return { d: gpts([
        [0, H], [0, 0], [W, 0], [W, H - hl], [W - sh, H], [W - a, H - hl], [W - a, a], [a, a], [a, H]]) };
    },
    leftUpArrow: function (W, H) {
      var m = Math.min(W, H);
      var hw = m * 0.18, hl = m * 0.28, sh = m * 0.09;
      var mx = W / 2, my = H / 2;
      return { d: gpts([
        [mx, 0], [mx + hw, hl], [mx + sh, hl], [mx + sh, my - sh],
        [W, my - sh], [W, my + sh], [mx + sh, my + sh], [mx + sh, H], [mx - sh, H],
        [mx - sh, my + sh], [hl, my + sh], [hl, my + hw], [0, my], [hl, my - hw],
        [hl, my - sh], [mx - sh, my - sh], [mx - sh, hl], [mx - hw, hl]]) };
    },
    notchedRightArrow: function (W, H) {
      var hx = W * 0.6, nx = W * 0.18, st = H * 0.25, sb = H * 0.75;
      return { d: gpts([[0, st], [hx, st], [hx, 0], [W, H / 2], [hx, H], [hx, sb], [0, sb], [nx, H / 2]]) };
    },
    chevron: function (W, H) {
      var k = W * 0.25;
      return { d: gpts([[0, 0], [W - k, 0], [W, H / 2], [W - k, H], [0, H], [k, H / 2]]) };
    },
    homePlate: function (W, H) {
      var k = W * 0.25;
      return { d: gpts([[0, 0], [W - k, 0], [W, H / 2], [W - k, H], [0, H]]) };
    },
    flowChartProcess: function (W, H) { return { d: gpts([[0, 0], [W, 0], [W, H], [0, H]]) }; },
    flowChartDecision: function (W, H) { return { d: gpts([[W / 2, 0], [W, H / 2], [W / 2, H], [0, H / 2]]) }; },
    flowChartTerminator: function (W, H) { var r = Math.min(W, H) / 2; return { d: grrect(W, H, r, r, r, r) }; },
    flowChartDocument: function (W, H) {
      return { d: 'M0 0L' + gnum(W) + ' 0L' + gnum(W) + ' ' + gnum(H * 0.85)
        + 'C' + gnum(W * 0.75) + ' ' + gnum(H) + ' ' + gnum(W * 0.25) + ' ' + gnum(H * 1.1)
        + ' 0 ' + gnum(H * 0.85) + 'Z' };
    },
    flowChartPredefinedProcess: function (W, H) {
      var a = W * 0.12, b = W * 0.88;
      return { d: gpts([[0, 0], [W, 0], [W, H], [0, H]]),
        detail: 'M' + gnum(a) + ' 0L' + gnum(a) + ' ' + gnum(H) + 'M' + gnum(b) + ' 0L' + gnum(b) + ' ' + gnum(H) };
    },
    flowChartInternalStorage: function (W, H) {
      return { d: gpts([[0, 0], [W, 0], [W, H], [0, H]]),
        detail: 'M0 ' + gnum(H * 0.2) + 'L' + gnum(W) + ' ' + gnum(H * 0.2)
          + 'M' + gnum(W * 0.2) + ' 0L' + gnum(W * 0.2) + ' ' + gnum(H) };
    },
    flowChartConnector: function (W, H) { return { d: gell(W / 2, H / 2, W / 2, H / 2) }; },
    flowChartSort: function (W, H) {
      return { d: gpts([[W / 2, 0], [W, H / 2], [W / 2, H], [0, H / 2]]),
        detail: 'M0 ' + gnum(H / 2) + 'L' + gnum(W) + ' ' + gnum(H / 2) };
    },
    flowChartExtract: function (W, H) { return { d: gpts([[W / 2, 0], [W, H], [0, H]]) }; },
    flowChartMerge: function (W, H) { return { d: gpts([[0, 0], [W, 0], [W / 2, H]]) }; },
    flowChartMagneticDisk: function (W, H) {
      var rx = W / 2, ry = Math.min(W, H) * 0.15;
      return { d: 'M0 ' + gnum(ry) + 'A' + gnum(rx) + ' ' + gnum(ry) + ' 0 0 1 ' + gnum(W) + ' ' + gnum(ry)
        + 'L' + gnum(W) + ' ' + gnum(H - ry) + 'A' + gnum(rx) + ' ' + gnum(ry) + ' 0 0 1 0 ' + gnum(H - ry) + 'Z',
        detail: gell(rx, ry, rx, ry) };
    },
    flowChartOffpageConnector: function (W, H) {
      return { d: gpts([[0, 0], [W, 0], [W, H * 0.7], [W / 2, H], [0, H * 0.7]]) };
    },
    wedgeRectCallout: function (W, H) {
      return { d: gpts([[0, 0], [W, 0], [W, H * 0.8], [W * 0.3, H * 0.8], [W * 0.12, H],
        [W * 0.22, H * 0.8], [0, H * 0.8]]) };
    },
    cloudCallout: function (W, H) {
      var t = H * 0.72;
      return { d: 'M' + gnum(W * 0.18) + ' ' + gnum(t * 0.85)
        + 'C' + gnum(W * 0.02) + ' ' + gnum(t * 0.85) + ' ' + gnum(W * 0.02) + ' ' + gnum(t * 0.6)
        + ' ' + gnum(W * 0.16) + ' ' + gnum(t * 0.57)
        + 'C' + gnum(W * 0.11) + ' ' + gnum(t * 0.3) + ' ' + gnum(W * 0.34) + ' ' + gnum(t * 0.24)
        + ' ' + gnum(W * 0.44) + ' ' + gnum(t * 0.36)
        + 'C' + gnum(W * 0.52) + ' ' + gnum(t * 0.13) + ' ' + gnum(W * 0.79) + ' ' + gnum(t * 0.15)
        + ' ' + gnum(W * 0.8) + ' ' + gnum(t * 0.4)
        + 'C' + gnum(W * 1.0) + ' ' + gnum(t * 0.4) + ' ' + gnum(W * 1.02) + ' ' + gnum(t * 0.85)
        + ' ' + gnum(W * 0.86) + ' ' + gnum(t * 0.85) + 'Z'
        + gell(W * 0.3, H * 0.88, W * 0.07, H * 0.08)
        + gell(W * 0.18, H * 0.97, W * 0.045, H * 0.05), rule: 'nonzero' };
    },
    flag: function (W, H) {
      var x0 = W * 0.09;
      return { d: gpts([[0, 0], [x0, 0], [x0, H], [0, H]])
        + 'M' + gnum(x0) + ' 0L' + gnum(W) + ' 0'
        + 'C' + gnum(W * 0.75) + ' ' + gnum(H * 0.2) + ' ' + gnum(W * 0.6) + ' ' + gnum(H * 0.1)
        + ' ' + gnum(W * 0.45) + ' ' + gnum(H * 0.28)
        + 'C' + gnum(W * 0.3) + ' ' + gnum(H * 0.45) + ' ' + gnum(W * 0.2) + ' ' + gnum(H * 0.4)
        + ' ' + gnum(x0) + ' ' + gnum(H * 0.5) + 'Z', rule: 'nonzero' };
    },
  };
  // ↑↑↑ 形状几何库 ↑↑↑

  var shapeSeq = 0;

  function shapeFlag(v) {
    return v === true || v === 1 || v === '1' || v === 'true' || v === 'on' || v === 'yes';
  }

  /** 给颜色叠透明度：hex / rgb 都能转成 rgba，其它原样返回。 */
  function rgbaOf(color, alpha) {
    var c = String(color === null || color === undefined ? '' : color).trim();
    var a = clamp(num(alpha, 1), 0, 1);
    var m = /^#([0-9a-fA-F]{3})$/.exec(c);
    if (m) {
      var h3 = m[1];
      return 'rgba(' + parseInt(h3.charAt(0) + h3.charAt(0), 16) + ',' + parseInt(h3.charAt(1) + h3.charAt(1), 16)
        + ',' + parseInt(h3.charAt(2) + h3.charAt(2), 16) + ',' + a + ')';
    }
    m = /^#([0-9a-fA-F]{6})$/.exec(c);
    if (m) {
      var h6 = m[1];
      return 'rgba(' + parseInt(h6.slice(0, 2), 16) + ',' + parseInt(h6.slice(2, 4), 16)
        + ',' + parseInt(h6.slice(4, 6), 16) + ',' + a + ')';
    }
    return c || ('rgba(0,0,0,' + a + ')');
  }

  /** 虚线样式 → SVG stroke-dasharray（按线宽等比，和 PowerPoint 观感接近）。 */
  function shapeDash(kind, sw) {
    var w = sw > 0 ? sw : 1;
    switch (kind) {
      case 'dash': return (w * 4) + ' ' + (w * 3);
      case 'longDash': return (w * 8) + ' ' + (w * 4);
      case 'dot': return (w * 0.1) + ' ' + (w * 2);
      case 'dashDot': return (w * 4) + ' ' + (w * 2) + ' ' + (w * 0.1) + ' ' + (w * 2);
      case 'roundDot': return (w * 0.1) + ' ' + (w * 2);
      default: return '';
    }
  }

  /**
   * 图片填充的图片地址。props.fillImage 是工程内相对路径，画布 / 导出各自把素材根
   * 通过 props.$assetBase 传进来（画布用 state.projectUrl，HTML 导出用 root_prefix），
   * 拼成能直接加载的 URL；已是绝对 URL 或 data: 的原样返回。
   */
  function fillImageHref(p) {
    var rel = String(p.fillImage || '').trim();
    if (!rel) return '';
    if (/^(https?:|data:|blob:|\/)/i.test(rel)) return rel;
    return String(p.$assetBase || '') + rel;
  }

  /** 渐变定义体：角度按 CSS 习惯（0° 左→右，90° 上→下）。 */
  function shapeGradient(uid, from, to, angle) {
    var a = num(angle, 90) * Math.PI / 180;
    var dx = Math.cos(a) / 2;
    var dy = Math.sin(a) / 2;
    return '<linearGradient id="' + uid + '" x1="' + (0.5 - dx) + '" y1="' + (0.5 - dy) + '"'
      + ' x2="' + (0.5 + dx) + '" y2="' + (0.5 + dy) + '">'
      + '<stop offset="0" stop-color="' + escAttr(from) + '"/>'
      + '<stop offset="1" stop-color="' + escAttr(to) + '"/></linearGradient>';
  }

  /**
   * 形状元素的内部 HTML。
   * 画布调用 shapeSvg(props, style, w, h)；HTML 导出把 style / 尺寸塞进 props 的
   * $style / $w / $h，经 renderFor('shape', props) 走到这里，两条路径共用同一实现。
   */
  function shapeSvg(props, style, w, h) {
    var p = props || {};
    var st = style || p.$style || {};
    var W = Math.max(1, num(w, num(p.$w, 220)));
    var H = Math.max(1, num(h, num(p.$h, 140)));
    var name = SHAPE_GEOMS[String(p.shape || '')] ? String(p.shape) : 'rect';
    var geom = SHAPE_GEOMS[name] || SHAPE_GEOMS.rect;
    var g = (typeof geom === 'function' ? geom(W, H, p, st) : geom) || {};
    return vectorSvg(p, st, W, H, g.d || '', g.detail || '', g.rule || 'evenodd');
  }

  /**
   * 路径元素（可编辑矢量轮廓）的内部 HTML。
   * 几何直接来自 props.d（SVG path 数据：M/L/C/Q/A/Z 都能画），坐标系与形状一致 ——
   * viewBox 铺满元素框，缩放元素即缩放路径。填充 / 描边 / 阴影 / 倒影与形状共用同一套属性。
   */
  function pathSvg(props, style, w, h) {
    var p = props || {};
    var st = style || p.$style || {};
    var W = Math.max(1, num(w, num(p.$w, 220)));
    var H = Math.max(1, num(h, num(p.$h, 140)));
    var rule = String(p.fillRule || '') === 'evenodd' ? 'evenodd' : 'nonzero';
    return vectorSvg(p, st, W, H, String(p.d || ''), '', rule);
  }

  /**
   * 连线箭头的一个头：按 paint 决定画法 —— fill 实心填充 / hollow 空心（白底 + 描边）/
   * stroke 开放（只描边，如依赖箭头）。d 是元素局部坐标下的路径（开放路径不带 Z）。
   */
  function connectorHeadSvg(d, paint, col, sw) {
    if (!d) return '';
    if (paint === 'hollow') {
      return '<path d="' + d + '" fill="#ffffff" stroke="' + escAttr(col) + '" stroke-width="' + sw
        + '" stroke-linejoin="miter"/>';
    }
    if (paint === 'stroke') {
      return '<path d="' + d + '" fill="none" stroke="' + escAttr(col) + '" stroke-width="' + sw
        + '" stroke-linecap="round" stroke-linejoin="round"/>';
    }
    return '<path d="' + d + '" fill="' + escAttr(col) + '"/>';
  }

  /**
   * 连线元素（元素间连线）的内部 HTML。
   * 几何已经在编辑期由 web/js/connector-geom.js 解析好，写进 props.d（主路径）与
   * props.arrowStartPath / props.arrowEndPath（两端的箭头）。坐标是元素局部 0..w / 0..h，
   * 箭头画法由 props.arrowStartPaint / arrowEndPaint 给出（实心 / 空心 / 开放）。
   * 这里只负责画：一条不填充的描边路径 + 两端的箭头；另叠一条加粗的透明路径当命中区，
   * 斜线两旁的空白角落才点不中（元素节点本身是 pointer-events:none）。
   */
  function connectorSvg(props, style, w, h) {
    var p = props || {};
    var st = style || p.$style || {};
    var W = Math.max(1, num(w, num(p.$w, 220)));
    var H = Math.max(1, num(h, num(p.$h, 140)));
    var d = String(p.d || '');
    if (!d) return '';
    var sw = Math.max(0, num(st.borderWidth, 2));
    var col = safeColor(st.borderColor, '') || '#2f6fed';
    var capMap = { butt: 'butt', round: 'round', square: 'square' };
    var joinMap = { miter: 'miter', round: 'round', bevel: 'bevel' };
    var cap = capMap[String(p.strokeCap || '')] || 'butt';
    var join = joinMap[String(p.strokeJoin || '')] || 'round';
    var dashKind = String(p.strokeDash || '');
    if (!dashKind && String(st.borderStyle || '') === 'dashed') dashKind = 'dash';
    var dash = shapeDash(dashKind, sw);
    var attrs = ' fill="none" stroke="' + escAttr(col) + '" stroke-width="' + sw
      + '" stroke-linecap="' + cap + '" stroke-linejoin="' + join + '"'
      + (dash ? ' stroke-dasharray="' + dash + '"' : '');
    var heads = connectorHeadSvg(p.arrowStartPath, p.arrowStartPaint, col, sw)
      + connectorHeadSvg(p.arrowEndPath, p.arrowEndPaint, col, sw);
    return '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" width="100%" height="100%"'
      + ' style="display:block;overflow:visible">'
      + '<path d="' + d + '"' + attrs + '/>'
      + heads
      + '<path d="' + d + '" fill="none" stroke="transparent" stroke-width="'
      + Math.max(12, sw + 10) + '" pointer-events="stroke"/>'
      + '</svg>';
  }

  /** 形状 / 路径共用的 SVG 组装：给定轮廓 d、附加描边线 detail 与填充规则。 */
  function vectorSvg(p, st, W, H, d, detail, rule) {

    var sw = num(st.borderWidth, 0);
    var strokeCol = safeColor(st.borderColor, '');
    var capMap = { round: 'round', square: 'square' };
    var joinMap = { round: 'round', bevel: 'bevel' };
    var cap = capMap[String(p.strokeCap || '')] || 'butt';
    var join = joinMap[String(p.strokeJoin || '')] || 'miter';
    var dashKind = String(p.strokeDash || '');
    if (!dashKind && String(st.borderStyle || '') === 'dashed') dashKind = 'dash';
    var dash = shapeDash(dashKind, sw);
    var hasStroke = sw > 0 && !!strokeCol;
    var strokeAttrs = hasStroke
      ? ' stroke="' + escAttr(strokeCol) + '" stroke-width="' + sw + '" stroke-linecap="' + cap
        + '" stroke-linejoin="' + join + '"' + (dash ? ' stroke-dasharray="' + dash + '"' : '')
      : ' stroke="none"';

    // style.fill 是模型常写错的别名键（引擎只认 background，见 element-schema.json 的 aliases）。
    // 落盘/读盘都会被改写过来，这里再兜一层，免得内存里的脏键渲染成没填充。
    var base = safeColor(st.background, '') || safeColor(st.fill, '');
    var fillType = String(p.fillType || 'solid');
    var defs = '';
    var fillAttr;
    if (fillType === 'none') {
      fillAttr = 'none';
    } else if (fillType === 'gradient') {
      shapeSeq += 1;
      var uid = 'acg' + shapeSeq;
      defs = '<defs>' + shapeGradient(uid, base || '#ffffff', safeColor(p.fillGradientTo, '#ffffff'), p.fillGradientAngle) + '</defs>';
      fillAttr = 'url(#' + uid + ')';
    } else if (fillType === 'image') {
      // 图片填充：把图拉伸到元素外框（0..W / 0..H）做成一个 pattern，再用轮廓当裁剪。
      // 与 PowerPoint 的图片填充「拉伸」是同一套映射 —— 图片铺满外接矩形，多出轮廓的部分被裁掉。
      var img = fillImageHref(p);
      if (img) {
        shapeSeq += 1;
        var iuid = 'aci' + shapeSeq;
        defs = '<defs><pattern id="' + iuid + '" patternUnits="userSpaceOnUse" x="0" y="0"'
          + ' width="' + W + '" height="' + H + '">'
          + '<image href="' + escAttr(img) + '" x="0" y="0" width="' + W + '" height="' + H
          + '" preserveAspectRatio="none"/></pattern></defs>';
        fillAttr = 'url(#' + iuid + ')';
      } else {
        fillAttr = 'none';
      }
    } else {
      fillAttr = base || 'none';
    }

    var fo = clamp(num(p.fillOpacity, 1), 0, 1);
    var fillAttrs = ' fill="' + fillAttr + '" fill-rule="' + rule + '"' + (fo < 1 ? ' fill-opacity="' + fo + '"' : '');

    var filter = '';
    if (shapeFlag(p.shadowOn)) {
      filter += 'drop-shadow(' + num(p.shadowX, 2) + 'px ' + num(p.shadowY, 3) + 'px ' + num(p.shadowBlur, 6) + 'px '
        + rgbaOf(safeColor(p.shadowColor, '#000000'), num(p.shadowOpacity, 0.35)) + ')';
    }
    if (shapeFlag(p.glowOn)) {
      filter += (filter ? ' ' : '') + 'drop-shadow(0 0 ' + Math.max(1, num(p.glowSize, 8)) + 'px '
        + rgbaOf(safeColor(p.glowColor, '#2f6fed'), 1) + ')';
    }

    var flip = '';
    if (shapeFlag(p.flipH)) flip += 'scaleX(-1) ';
    if (shapeFlag(p.flipV)) flip += 'scaleY(-1)';

    var inner = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" width="100%" height="100%"'
      + ' style="display:block;overflow:visible">'
      + defs
      + (d ? '<path d="' + d + '"' + fillAttrs + strokeAttrs + '/>' : '')
      + (detail ? '<path d="' + detail + '" fill="none"' + strokeAttrs + '/>' : '')
      + '</svg>';

    var wrapStyle = 'position:relative;width:100%;height:100%;overflow:visible'
      + (filter ? ';filter:' + filter : '')
      + (flip ? ';transform:' + flip : '');

    var ref = '';
    if (shapeFlag(p.reflectOn)) {
      var rs = clamp(num(p.reflectSize, 50), 0, 100) / 100;
      var refH = Math.max(1, H * rs);
      var gap = num(p.reflectGap, 0);
      var refO = clamp(num(p.reflectOpacity, 0.35), 0, 1);
      var mask = 'linear-gradient(to bottom, rgba(0,0,0,1) 0%, rgba(0,0,0,0) 100%)';
      ref = '<div style="position:absolute;left:0;top:100%;width:100%;height:' + trimZero(refH)
        + 'px;margin-top:' + gap + 'px;overflow:hidden;pointer-events:none;opacity:' + refO
        + ';-webkit-mask-image:' + mask + ';mask-image:' + mask + '">'
        + '<div style="width:100%;height:' + trimZero(H) + 'px;transform:scaleY(-1)">' + inner + '</div></div>';
    }

    return '<div class="ac-shape" style="' + wrapStyle + '">' + inner + ref + '</div>';
  }

  /**
   * 只要形状的轮廓路径（没有填充、描边、渐变）。图片蒙版拿它当裁剪区域：
   * props 里给个 shape 名，返回 { d, rule }。
   */
  function shapePath(props, w, h) {
    var p = props || {};
    var W = Math.max(1, num(w, num(p.$w, 220)));
    var H = Math.max(1, num(h, num(p.$h, 140)));
    var name = SHAPE_GEOMS[String(p.shape || '')] ? String(p.shape) : 'rect';
    var geom = SHAPE_GEOMS[name] || SHAPE_GEOMS.rect;
    var g = (typeof geom === 'function' ? geom(W, H, p, p.$style || {}) : geom) || {};
    return { d: g.d || '', rule: g.rule || 'evenodd' };
  }

  ACRender.shapeSvg = shapeSvg;
  ACRender.pathSvg = pathSvg;
  ACRender.connectorSvg = connectorSvg;
  ACRender.shapePath = shapePath;
  ACRender.SHAPE_NAMES = SHAPE_NAMES;
  ACRender.SHAPE_LABELS = SHAPE_LABELS;

  // ---------------------------------------------------------------- 统一挂载
  /** 按元素类型选择渲染器；供 canvas.js / 导出 HTML 的挂载脚本共用。 */
  function renderFor(type, props) {
    var p = props || {};
    switch (type) {
      case 'text': return '<div class="ac-text">' + richText(p.text, p) + '</div>';
      case 'table': return tableHtml(p);
      case 'code': return codeBlock(p);
      case 'chart': return chartSvg(p);
      case 'shape': return shapeSvg(p, p.$style, p.$w, p.$h);
      case 'path': return pathSvg(p, p.$style, p.$w, p.$h);
      case 'connector': return connectorSvg(p, p.$style, p.$w, p.$h);
      default: return esc(p.text);
    }
  }

  /**
   * 把页面上所有带 data-ac-props 的元素就地渲染成真内容。
   * 载荷由服务端写进属性（而非脚本标签），属性值经 HTML 转义，不会被内容提前闭合；
   * 节点的 data-type 决定用哪个渲染器，重复调用无副作用。
   */
  function mountAll(root) {
    var doc = root || (typeof document === 'undefined' ? null : document);
    if (!doc || !doc.querySelectorAll) return;
    var nodes = doc.querySelectorAll('[data-ac-props]');
    for (var i = 0; i < nodes.length; i += 1) {
      var host = nodes[i];
      if (host.getAttribute('data-ac-mounted') === '1') continue;
      var props = {};
      try { props = JSON.parse(host.getAttribute('data-ac-props') || '{}') || {}; } catch (e) { props = {}; }
      host.innerHTML = renderFor(host.getAttribute('data-type') || '', props);
      host.setAttribute('data-ac-mounted', '1');
    }
  }

  ACRender.renderFor = renderFor;
  ACRender.mountAll = mountAll;

  // ---------------------------------------------------------------- 自举
  injectCss();
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () { injectCss(); mountAll(); });
    } else {
      mountAll();
    }
  }

  global.ACRender = ACRender;
}(typeof window !== 'undefined' ? window : this));