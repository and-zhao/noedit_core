"""全局路径与应用常量。

路径默认相对「软件安装目录」（本文件夹）解析，不访问网络位置。
打包成绿色目录后，「软件安装目录」= 主程序 exe 所在目录。
打包成 Agent Skill 时会注入一段前奏，把可写运行数据（NOEDIT_CORE_ROOT）
默认指到用户主目录；默认工程目录则由 projects_root() 按 skill 安装位置自动获取。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

APP_NAME = "NoEdit"
# 应用标识符：数据目录名等依赖它，保持稳定。
APP_ID = "noedit_core"
VERSION = "0.2.0"
SCHEMA_VERSION = 1

# 根目录覆盖：把 data/ 与 web/ 指到别处时用（默认 = 本核心包目录 noedit_core/）。
ROOT_ENV = "NOEDIT_CORE_ROOT"

# 默认的工程根目录：界面「打开工程」默认停在这里，并把它下面的工程列出来。
# 故意写成相对地址（相对软件安装目录 APP_ROOT = noedit_core/noedit_core），
# 换台机器/换盘符都不用改代码。需要指到别处时用环境变量覆盖（绝对或相对路径都行）。
PROJECTS_ENV = "NOEDIT_CORE_PROJECTS"
DEFAULT_PROJECTS_REL = "../../projects"


def _app_root() -> Path:
    override = os.environ.get(ROOT_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    # 打包（PyInstaller）后 __file__ 指向包内，必须改用 exe 的位置：
    # 否则 data/ 会落到临时解包目录，每次运行都换地方，等于没有数据。
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _bundle_dir() -> Path:
    """只读资源（web/ 等）的真实所在目录，**永远不跟随** NOEDIT_CORE_ROOT。

    PyInstaller 下是解包目录 _MEIPASS；源码运行时恒为包目录 noedit_core/noedit_core/。
    这样即便用 NOEDIT_CORE_ROOT 把可写的 data/ 移到用户目录，
    web/ 图标库与渲染资源仍能从包内取到。
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base).resolve()
    return Path(__file__).resolve().parent.parent


# 打包成 Agent Skill 后，skill 目录 = 含本包、且与 SKILL.md 同级的那一层
# （内含 main.py / SKILL.md）。默认工程目录就取它与 skill 同级的位置。
SKILL_MARKER = "SKILL.md"


def _skill_dir() -> Path | None:
    """skill 实体所在层（打包后 = 含 main.py / SKILL.md 的那一层）。

    用 __file__ 定位，**不跟随** NOEDIT_CORE_ROOT：可写数据被指到用户目录后，
    仍要能按 skill 的真实安装位置算出默认工程目录。
    非 skill 场景（PyInstaller 桌面版、源码仓库）返回 None。
    """
    if getattr(sys, "frozen", False):
        return None
    return Path(__file__).resolve().parent.parent.parent


def _skill_default_projects() -> Path | None:
    """打包成 skill 时给出的默认工程目录：与 skill 文件夹同级（自动获取）。

    例如 skill 装在 ~/.trae-cn/skills/noedit-core/ 时，
    默认工程目录 = ~/.trae-cn/skills/noedit_core/。
    旁边没有 SKILL.md（不是打包好的 skill）就返回 None，交给调用方退回旧相对地址。
    """
    skill = _skill_dir()
    if skill is None or not (skill / SKILL_MARKER).is_file():
        return None
    return skill.parent / APP_ID


APP_ROOT: Path = _app_root()
BUNDLE_DIR: Path = _bundle_dir()
DATA_DIR: Path = APP_ROOT / "data"
USERS_DIR: Path = DATA_DIR / "users"
ACCOUNTS_FILE: Path = DATA_DIR / "accounts.json"
LOG_FILE: Path = DATA_DIR / "app.log"

# UI 服务注册文件：serve 启动时写入 host/port/pid/当前工程，退出时删除。
# 外部进程（agent / 脚本）按它找到正在运行的本机 UI，再调 /api/ui/*。
UI_FILE: Path = DATA_DIR / "ui.json"

# 工程锁文件目录。锁必须放在「界面进程」与「扩展进程」都能算出同一位置的地方，
# 所以挂在 data/ 下（data/ 的位置由 ATOMIC_CANVAS_ROOT 统一决定）；
# 各自放自己的缓存目录里会变成两把互不相干的锁，等于没锁。
LOCK_DIR: Path = DATA_DIR / "locks"

# 前端目录：绿色目录里放一份外置副本方便直接改；没有就退回包内那份。
WEB_DIR: Path = APP_ROOT / "web" if (APP_ROOT / "web").is_dir() else BUNDLE_DIR / "web"

# 扩展源码目录（本核心未使用，保留常量）。
EXTENSIONS_DIR: Path = APP_ROOT / "extensions"

# 插件目录：一个子目录一个插件（内含 plugin.json 与它自己的 HTML/JS/CSS）。
# 同样放在「软件安装目录」下，绿色目录里直接丢文件夹就生效；
# 它同时是本地服务 /plugins/ 的根（插件页面由这里供给浏览器沙箱加载）。
PLUGINS_DIR: Path = APP_ROOT / "plugins"

# 配置目录：插件配置的固定落点（一个插件一个文件，格式统一，见 app/plugin_settings.py）。
# 与 plugins/ 同级放在「软件安装目录」下：绿色目录里可以直接打开改，改了界面读到的就是它。
CONFIG_DIR: Path = APP_ROOT / "config"

# 工程文件夹内的固定结构
MANIFEST_NAME = "project.manifest.json"
CANVAS_HTML_NAME = "index.html"
ASSETS_DIR_NAME = "assets"
EXPORT_DIR_NAME = "export"

# 账户目录下的素材库默认地址：添加素材 / 选填充图时文件对话框默认开在这里，
# 用来给「素材库」一个确定的本地落点（库本身只存引用，不搬文件本体）。
LIBRARY_DIR_NAME = "library"

# 支持的素材类型（拖入后生成对应原子元素）
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"}
VIDEO_EXT = {".mp4", ".m4v", ".webm", ".ogg", ".ogv", ".mov", ".mkv", ".avi"}
AUDIO_EXT = {".mp3", ".wav", ".aac", ".flac", ".m4a"}
TABLE_EXT = {".csv", ".tsv", ".xlsx"}
CODE_EXT = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".h", ".cpp", ".cs",
    ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".sh", ".ps1", ".sql",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".css", ".md",
}


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_text(target: Path, text: str) -> None:
    """先写同目录临时文件、再 os.replace 顶上。

    原子替换是整套并发方案的地基：读的一方永远看不到写了一半的文件。
    但 Windows 上替换与「正打开着该文件的人」互斥（句柄不带删除共享），
    所以读写两侧都要带重试——这类占用都是毫秒级的。

    放在 paths 里是因为写盘的两条线都要用它：工程文件（projects）与账户数据（storage）。
    """
    ensure_dir(target.parent)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(tmp, target)
            return
        except OSError:
            if attempt == 4:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.04)


def ensure_base_dirs() -> None:
    ensure_dir(DATA_DIR)
    ensure_dir(USERS_DIR)


def user_dir(account_id: str) -> Path:
    """账户私有目录：不同账户数据完全隔离。"""
    return USERS_DIR / account_id


def ensure_user_dirs(account_id: str) -> Path:
    root = ensure_dir(user_dir(account_id))
    ensure_dir(root / "projects")
    ensure_dir(root / "templates")
    ensure_dir(root / LIBRARY_DIR_NAME)
    return root


def projects_root() -> Path:
    """默认工程根目录（绝对路径）。相对地址一律按软件安装目录 APP_ROOT 解析。

    优先级：环境变量 NOEDIT_CORE_PROJECTS ＞ skill 同级目录（打包成 skill 后自动获取）
    ＞ 相对软件安装目录的 ../../projects（源码仓库场景）。
    """
    raw = os.environ.get(PROJECTS_ENV, "").strip()
    p = Path(raw).expanduser() if raw else (_skill_default_projects() or Path(DEFAULT_PROJECTS_REL))
    if not p.is_absolute():
        p = APP_ROOT / p
    return p.resolve()
