#!/usr/bin/env python3
"""Task Verge deterministic app recognition rules — stdlib only.

Three-stage pipeline for app recognition, replacing DeepSeek calls:
  1. KNOWN_APPS lookup (exact match on exe name)
  2. Task-keyword category mapping (no AI needed)
  3. Remaining → DeepSeek fallback (unchanged)

Activate via env: TASKVERGE_APP_RULES=1 (default: off)
"""

import re as _re

# ---------------------------------------------------------------------------
# Stage 1: KNOWN_APPS — common Windows applications pre-classified
# Format: "lowercase_exe" → (category, subcategory)
# ---------------------------------------------------------------------------

KNOWN_APPS = {
    # --- 开发 / Development ---
    "code.exe": ("开发", "代码编辑器"),
    "devenv.exe": ("开发", "IDE"),
    "msbuild.exe": ("开发", "IDE"),
    "idea64.exe": ("开发", "IDE"),
    "pycharm64.exe": ("开发", "IDE"),
    "webstorm64.exe": ("开发", "IDE"),
    "eclipse.exe": ("开发", "IDE"),
    "android studio.exe": ("开发", "IDE"),
    "sublime_text.exe": ("开发", "代码编辑器"),
    "notepad++.exe": ("开发", "代码编辑器"),
    "vim.exe": ("开发", "代码编辑器"),
    "cursor.exe": ("开发", "代码编辑器"),
    "trae solo cn.exe": ("开发", "代码编辑器"),
    "studio64.exe": ("开发", "IDE"),
    "claude.exe": ("开发", "AI 辅助"),
    "terminal.exe": ("开发", "终端"),
    "powershell.exe": ("开发", "终端"),
    "cmd.exe": ("开发", "终端"),
    "git-bash.exe": ("开发", "终端"),
    "wsl.exe": ("开发", "终端"),
    "node.exe": ("开发", "运行时"),
    "python.exe": ("开发", "运行时"),
    "git.exe": ("开发", "版本管理"),
    "sourcetree.exe": ("开发", "版本管理"),
    "githubdesktop.exe": ("开发", "版本管理"),
    "docker desktop.exe": ("开发", "容器"),

    # --- 学习办公 / Office & Productivity ---
    "winword.exe": ("学习办公", "文档写作"),
    "excel.exe": ("学习办公", "表格处理"),
    "powerpnt.exe": ("学习办公", "演示文稿"),
    "outlook.exe": ("学习办公", "邮件与日历"),
    "onenote.exe": ("学习办公", "笔记与知识管理"),
    "obsidian.exe": ("学习办公", "笔记与知识管理"),
    "notion.exe": ("学习办公", "笔记与知识管理"),
    "typora.exe": ("学习办公", "笔记与知识管理"),
    "evernote.exe": ("学习办公", "笔记与知识管理"),
    "yuque.exe": ("学习办公", "笔记与知识管理"),
    "xmind.exe": ("学习办公", "思维导图"),
    "wps.exe": ("学习办公", "文档写作"),
    "et.exe": ("学习办公", "表格处理"),
    "wpp.exe": ("学习办公", "演示文稿"),

    # --- 浏览器 / Browsers ---
    "chrome.exe": ("浏览器", "网页浏览"),
    "msedge.exe": ("浏览器", "网页浏览"),
    "firefox.exe": ("浏览器", "网页浏览"),
    "brave.exe": ("浏览器", "网页浏览"),
    "opera.exe": ("浏览器", "网页浏览"),

    # --- 设计 / Design ---
    "photoshop.exe": ("设计", "图像编辑"),
    "illustrator.exe": ("设计", "矢量绘图"),
    "figma.exe": ("设计", "UI 设计"),
    "blender.exe": ("设计", "3D 建模"),
    "sketchup.exe": ("设计", "3D 建模"),
    "gimp-2.10.exe": ("设计", "图像编辑"),
    "inkscape.exe": ("设计", "矢量绘图"),

    # --- 音视频 / Media ---
    "obs64.exe": ("音视频", "录播与直播"),
    "premiere pro.exe": ("音视频", "视频编辑"),
    "afterfx.exe": ("音视频", "视频特效"),
    "audacity.exe": ("音视频", "音频编辑"),
    "vlc.exe": ("音视频", "媒体播放"),
    "spotify.exe": ("音视频", "音乐流媒体"),

    # --- 沟通协作 / Communication ---
    "wechat.exe": ("沟通协作", "即时通讯"),
    "wechatweb.exe": ("沟通协作", "即时通讯"),
    "dingtalk.exe": ("沟通协作", "即时通讯"),
    "feishu.exe": ("沟通协作", "即时通讯"),
    "teams.exe": ("沟通协作", "视频会议"),
    "zoom.exe": ("沟通协作", "视频会议"),
    "slack.exe": ("沟通协作", "团队协作"),
    "discord.exe": ("沟通协作", "社区"),

    # --- 游戏 / Gaming ---
    "steam.exe": ("游戏", "游戏平台"),
    "bf6.exe": ("游戏", "射击"),
    "valorant.exe": ("游戏", "射击"),
    "league of legends.exe": ("游戏", "MOBA"),
    "minecraft.exe": ("游戏", "沙盒"),

    # --- 文件管理 / File Management ---
    "7zfm.exe": ("文件管理", "压缩工具"),
    "everything.exe": ("文件管理", "文件搜索"),

    # --- 阅读 / Reading ---
    "acrobat.exe": ("阅读", "PDF 阅读"),
    "foxitphantompdf.exe": ("阅读", "PDF 阅读"),
    "sumatrapdf.exe": ("阅读", "PDF 阅读"),
    "calibre.exe": ("阅读", "电子书管理"),

    # --- 云存储 / Cloud Storage ---
    "onedrive.exe": ("云存储", "文件同步"),
    "dropbox.exe": ("云存储", "文件同步"),
}

# ---------------------------------------------------------------------------
# Stage 2: Task keyword → category mapping
# ---------------------------------------------------------------------------

TASK_KEYWORDS = [
    (_re.compile(r"代码|编程|python|java|go\b|rust|c\+\+|前端|后端|脚本|算法|debug|api|框架|数据库|sql",
                _re.IGNORECASE), ["开发"]),
    (_re.compile(r"文档|写作|文章|报告|论文|ppt|word|excel|演示|笔记|记录|总结",
                _re.IGNORECASE), ["学习办公/文档写作", "学习办公/笔记与知识管理"]),
    (_re.compile(r"阅读|看书|读书|pdf|电子书|论文阅读",
                _re.IGNORECASE), ["阅读"]),
    (_re.compile(r"设计|画图|海报|ps|figma|ui|ux|视频|剪辑|音频|音乐",
                _re.IGNORECASE), ["设计", "音视频"]),
    (_re.compile(r"沟通|会议|周会|汇报|面试|联系|对接",
                _re.IGNORECASE), ["沟通协作"]),
    (_re.compile(r"英语|听力|单词|四级|六级|雅思|托福|背词|作文|翻译",
                _re.IGNORECASE), ["学习办公"]),
    (_re.compile(r"安装|配置|部署|环境|linux|docker|nginx|服务器|运维",
                _re.IGNORECASE), ["开发"]),
]

# Category → default apps (without needing AI)
CATEGORY_DEFAULT_APPS = {
    "开发": ["code.exe", "terminal.exe", "powershell.exe"],
    "开发/代码编辑器": ["code.exe", "notepad++.exe", "sublime_text.exe"],
    "开发/IDE": ["code.exe", "studio64.exe"],
    "开发/终端": ["terminal.exe", "powershell.exe", "cmd.exe"],
    "学习办公/文档写作": ["winword.exe", "wps.exe"],
    "学习办公/表格处理": ["excel.exe", "et.exe"],
    "学习办公/笔记与知识管理": ["obsidian.exe", "onenote.exe", "notion.exe"],
    "浏览器": ["chrome.exe", "msedge.exe"],
    "设计": ["photoshop.exe", "figma.exe"],
    "音视频": ["obs64.exe", "vlc.exe"],
    "沟通协作": ["wechat.exe", "teams.exe"],
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
import re as _re


def preclassify_apps(apps):
    """Classify apps using KNOWN_APPS lookup. Returns (classified, remaining).

    classified: {category_subcategory: [exe_names]}
    remaining: apps not found in KNOWN_APPS
    """
    classified = {}
    remaining = []

    for app in apps:
        exe = (app.get("exe") or "").strip()
        if not exe:
            remaining.append(app)
            continue

        key = exe.lower()
        if key in KNOWN_APPS:
            cat, sub = KNOWN_APPS[key]
            label = cat + "/" + sub
            classified.setdefault(label, []).append(exe)
        else:
            remaining.append(app)

    return classified, remaining


def smart_filter_tasks(tasks):
    """Pre-assign categories to tasks based on title keywords.

    Returns: {task_index: [category_labels]}
    """
    result = {}
    for task in tasks:
        idx = task.get("index", task.get("task_index", -1))
        if idx < 0:
            continue
        title = (task.get("title") or task.get("text") or "").strip()
        if not title:
            continue

        matched = set()
        for pattern, cats in TASK_KEYWORDS:
            if pattern.search(title):
                for c in cats:
                    matched.add(c)

        if matched:
            result[idx] = sorted(matched)

    return result


def fallback_apps_for_categories(category_labels, available_apps, user_history=None):
    """Map categories to app exe names using CATEGORY_DEFAULT_APPS + user_history.

    No AI call needed. Uses pre-built mapping + learned history.
    """
    history = user_history or {}
    result = set()
    combined_key = "|".join(sorted(category_labels)) or "default"

    for label in category_labels:
        # Check user history first (learned from previous sessions)
        for key in (label, combined_key):
            if key not in history: continue
            result.update(h["exe"] if isinstance(h, dict) else h for h in history.get(key, [])
                         if isinstance(h, (str, dict)))

        # Check default mapping
        if label in CATEGORY_DEFAULT_APPS:
            result.update(CATEGORY_DEFAULT_APPS[label])

        # Check parent category (e.g. "开发/IDE" → check "开发" too)
        if "/" in label:
            parent = label.split("/")[0]
            if parent in CATEGORY_DEFAULT_APPS:
                result.update(CATEGORY_DEFAULT_APPS[parent])

    # Filter to only apps that actually exist on this machine
    valid_exes = {a.get("exe", "").lower(): a.get("exe", "") for a in available_apps if a.get("exe")}
    filtered = []
    for exe in result:
        exe_lower = exe.lower()
        if exe_lower in valid_exes:
            filtered.append(valid_exes[exe_lower])

    return list(dict.fromkeys(filtered))  # dedupe preserving order


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Test preclassify_apps
    test_apps = [
        {"exe": "Obsidian.exe", "name": "Obsidian"},
        {"exe": "Code.exe", "name": "VS Code"},
        {"exe": "UnknownApp.exe", "name": "Unknown"},
        {"exe": "Chrome.exe", "name": "Chrome"},
        {"exe": "WeChat.exe", "name": "WeChat"},
    ]
    classified, remaining = preclassify_apps(test_apps)
    print("=== preclassify_apps ===")
    print("Classified ({}/{}):".format(
        sum(len(v) for v in classified.values()), len(test_apps)))
    for label, exes in classified.items():
        print("  {}: {}".format(label, exes))
    print("Remaining:", [a["exe"] for a in remaining])

    # Test smart_filter_tasks
    test_tasks = [
        {"index": 0, "title": "完成 Python 基础练习题"},
        {"index": 1, "title": "写周报和会议记录"},
        {"index": 2, "title": "阅读论文"},
        {"index": 3, "title": "随便做点事"},
    ]
    task_cats = smart_filter_tasks(test_tasks)
    print("\n=== smart_filter_tasks ===")
    for idx, cats in task_cats.items():
        print("  Task[{}]: {}".format(idx, cats))

    # Test fallback_apps_for_categories
    apps = fallback_apps_for_categories(
        ["开发/IDE", "学习办公/笔记与知识管理"],
        [{"exe": "Code.exe"}, {"exe": "Obsidian.exe"}, {"exe": "Pycharm64.exe"}],
    )
    print("\n=== fallback_apps_for_categories ===")
    print("  Apps:", apps)

    # Summary
    ai_saved = (len(remaining) < len(test_apps)) or task_cats
    print("\nSummary: AI calls saved = {}".format(ai_saved))
