#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公考日报 · 时政要闻每日抓取脚本

产出：
    data/YYYY-MM-DD.js    当天的 10 条时政要闻（网页直接读取）
    data/manifest.js      可用日期清单（网页据此做历史归档与更新检查）

设计原则
--------
1. 只用 Python 标准库，GitHub Actions 里零依赖可直接跑。
2. 多源冗余：任一来源挂掉都不影响出稿，按优先级依次补齐到 10 条。
3. 人工兜底：data/manual/YYYY-MM-DD.json 里写的内容优先级最高，
   抓取全挂时也能保证当天的页面照常发布、不断更。
4. 永不抛未捕获异常：抓取失败以退出码 0 结束并打印醒目告警，
   避免定时任务变红、也避免把上一期的数据覆盖成空。

用法
----
    python scripts/fetch_daily.py                 # 抓取今天（北京时间）
    python scripts/fetch_daily.py --date 2026-09-11
    python scripts/fetch_daily.py --offline        # 只用人工文件，不联网
    python scripts/fetch_daily.py --selftest       # 用内置样例自检解析器
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
MANUAL = os.path.join(DATA, "manual")
PER_DAY = 10
TIMEOUT = 15
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36  GongkaoDailyFetcher/1.0")
BJT = dt.timezone(dt.timedelta(hours=8))

# ---------------------------------------------------------------- 分类打标

# 分类打标：按「越具体越靠前」排序，命中即返回。
# 注意：这里刻意不把领导人姓名作为关键词，否则「习近平签署命令」这类
# 纯国内时政会被误判成外交类。外交类只认真正的外事信号词。
TAG_RULES = [
    ("国际外交", ["致贺电", "通电话", "会见", "会谈", "峰会", "外交", "联合国", "上合组织",
                  "东盟", "金砖", "大使", "国事访问", "双边关系", "联合声明", "总统", "首相",
                  "外长", "驻华", "国际社会", "全球治理"]),
    ("经济数据", ["CPI", "PPI", "GDP", "同比", "环比", "统计局", "景气指数", "社会消费品",
                  "财政收入", "外贸进出口", "工业增加值", "采购经理指数"]),
    ("经济金融", ["央行", "人民银行", "货币政策", "金融监管", "证监会", "外汇局", "信贷",
                  "利率", "汇率", "债券", "上市公司", "金融强国"]),
    ("民生保障", ["医保", "社保", "养老保险", "长护险", "长期护理", "育儿补贴", "低保",
                  "救助", "以旧换新", "消费补贴", "生育保险", "养老金", "住房保障"]),
    ("民生就业", ["新职业", "新工种", "就业", "人社部", "招聘", "职业技能", "农民工",
                  "灵活就业", "创业带动"]),
    ("法治建设", ["条例", "法律", "规定", "办法", "国务院令", "修订", "执法检查", "立法",
                  "最高人民法院", "最高人民检察院", "检察机关", "印发《"]),
    ("交通运输", ["铁路", "高铁", "机场", "公路", "地铁", "民航", "物流", "港口", "春运"]),
    ("科技教育", ["科技", "教育", "航天", "卫星", "人工智能", "5G", "量子", "专利",
                  "空间站", "载人", "创新成果", "高等教育", "教师"]),
    ("粮食安全", ["粮食", "农业", "耕地", "丰收", "乡村振兴", "种业", "农民", "秋粮", "夏粮"]),
    ("生态文明", ["生态", "环境", "环保", "碳达峰", "碳中和", "污染", "绿水青山", "生物多样性"]),
    ("海洋维权", ["海警", "海洋", "南海", "公海", "渔业", "岛礁"]),
    ("政治建设", ["全国人大", "全国政协", "统战", "民族", "宗教", "基层治理", "社会主义民主",
                  "民族团结", "协商民主"]),
    ("人事任免", ["任免", "任命", "免去", "国家工作人员"]),
]
DEFAULT_TAG = "时政要闻"

# 与公考无关的娱乐/体育/社会猎奇类黑名单
BLACKLIST = ["明星", "绯闻", "综艺", "票房", "选秀", "网游", "彩票", "球赛", "转会",
             "网剧", "带货", "直播带货", "小道消息"]

# ------------------------------------------------------------------ 时政相关性打分
# 通用新闻源（尤其是滚动新闻）里混有大量图片新闻、非遗手作、风光摄影，
# 这些内容对公考备考毫无价值。用打分把「真正的时政」筛出来。
SCORE_POSITIVE = [
    (3, ["习近平", "李强", "赵乐际", "王沪宁", "蔡奇", "丁薛祥", "李希", "韩正",
         "中共中央", "国务院", "全国人大", "全国政协", "中央军委", "中央办公厅",
         "国家发展改革委", "国家发改委", "财政部", "中国人民银行", "教育部",
         "人力资源社会保障部", "国家医保局", "商务部", "农业农村部", "国家统计局",
         "最高人民法院", "最高人民检察院", "外交部", "国防部"]),
    (2, ["会议", "全会", "常委会", "决定", "印发", "发布", "通知", "意见", "规划",
         "条例", "办法", "方案", "部署", "强调", "调研", "签署", "讲话", "致辞",
         "新闻发布会", "座谈会", "执法检查", "审议", "表决", "白皮书", "开幕式",
         "峰会", "会见", "会谈", "致贺电", "通电话", "国事访问"]),
    (2, ["CPI", "PPI", "GDP", "同比", "环比", "增长", "就业", "医保", "社保", "养老",
         "生育", "粮食", "耕地", "进出口", "外资", "民营经济", "科技创新", "高铁",
         "铁路", "航天", "发射", "碳达峰", "碳中和", "乡村振兴", "共同富裕"]),
]
SCORE_NEGATIVE = [
    (5, ["组图", "图集", "掠影", "镜头", "美景", "风光", "花海", "梯田", "秋色", "雪景",
         "打卡", "花絮", "走红", "亮相", "引人关注", "传承人", "技艺", "非遗", "手作",
         "美食", "采摘", "萌宠", "趣闻", "奇观", "潮汐树", "摄影", "画来", "入画",
         # 健康养生 / 生活消费 / 情感类，实测会从综合新闻源混进来
         "养生", "进补", "秋燥", "春困", "祛湿", "食补", "护肝", "养肝", "伤肝",
         "调理", "防止脱发", "失眠", "减肥", "减脂", "瘦身", "穿搭", "婆媳",
         "星座", "属相", "家常菜", "食谱", "小妙招", "别乱", "这样吃",
         "生活费", "好物推荐", "种草", "攻略"]),
    (3, ["图片", "视觉", "影像", "直播回放", "误区", "警惕", "提醒", "请注意", "别踩坑"]),
]
# 形如「广西三江侗乡：梯田染金入画来」的地名+图说式标题，基本是图片新闻
PHOTO_TITLE_RE = re.compile(r"^[\u4e00-\u9fff]{2,10}[：:].{0,30}(来|美|景|图|画|色)$")


def score_item(title: str, summary: str = "") -> int:
    """给一条新闻打「时政相关性」分，分越高越值得进每日十条。"""
    text = title + " " + (summary or "")
    s = 0
    for w, kws in SCORE_POSITIVE:
        if any(k in text for k in kws):
            s += w
    for w, kws in SCORE_NEGATIVE:
        if any(k in text for k in kws):
            s -= w
    if PHOTO_TITLE_RE.match(title):
        s -= 4
    if len(title) < 14:          # 过短的标题多半是快讯或栏目名
        s -= 1
    return s


def make_tag(text: str) -> str:
    for tag, kws in TAG_RULES:
        for kw in kws:
            if kw in text:
                return tag
    return DEFAULT_TAG


# ---------------------------------------------------------------- 工具

def log(msg: str) -> None:
    print("[公考日报] " + msg, flush=True)


def warn(msg: str) -> None:
    print("[公考日报][警告] " + msg, flush=True)


def http_get(url: str, retries: int = 2) -> str | None:
    """取回文本；自动尝试 utf-8 / gb18030 解码。失败返回 None。"""
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml,application/json,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
            for enc in ("utf-8", "gb18030"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001  网络问题一律吞掉，走下一源
            last = e
            time.sleep(1.2 * (i + 1))
    warn("取回失败 %s（%s）" % (url.split("?")[0][:70], last))
    return None


def strip_tags(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    s = s.replace("\u3000", " ").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def shorten(text: str, n: int = 170) -> str:
    text = strip_tags(text)
    if len(text) <= n:
        return text
    cut = text[:n]
    for p in ("。", "！", "？", "；"):
        i = cut.rfind(p)
        if i > n * 0.55:
            return cut[:i + 1]
    return cut.rstrip("，、,;；") + "。"


def norm_key(title: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", title)[:26]


# ---------------------------------------------------------------- 解析器

TAG_RE = re.compile(r"(?s)<item[^>]*>(.*?)</item>")
FIELD_RE = {
    "title": re.compile(r"(?s)<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>"),
    "link": re.compile(r"(?s)<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>"),
    "desc": re.compile(r"(?s)<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>"),
    "date": re.compile(r"(?s)<(?:pubDate|dc:date|published|updated)>(.*?)</"),
}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def parse_date(s: str):
    """从 RSS/Atom 的日期串里取出 datetime（UTC 无关，只用于比较新旧）。"""
    s = (s or "").strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", s)
    if m and m.group(2)[:3] in MONTHS:
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(2)[:3]], int(m.group(1)))
        except ValueError:
            return None
    return None


def parse_rss(xml: str, source: str) -> list[dict]:
    """兼容 RSS 2.0 / Atom 的轻量解析（标题、链接、摘要、发布时间）。"""
    items = []
    for block in TAG_RE.findall(xml)[:60]:
        t = FIELD_RE["title"].search(block)
        l = FIELD_RE["link"].search(block)
        d = FIELD_RE["desc"].search(block)
        p = FIELD_RE["date"].search(block)
        title = strip_tags(t.group(1)) if t else ""
        if len(title) < 8:
            continue
        items.append({
            "title": title,
            "summary": shorten(d.group(1)) if d else "",
            "source": source,
            "url": (l.group(1).strip() if l else ""),
            "pub": parse_date(p.group(1)) if p else None,
        })
    if not items:  # Atom 兜底
        for m in re.finditer(r"(?s)<entry[^>]*>(.*?)</entry>", xml):
            b = m.group(1)
            t = re.search(r"(?s)<title[^>]*>(.*?)</title>", b)
            l = re.search(r'(?s)<link[^>]*href="([^"]+)"', b)
            s = re.search(r"(?s)<(?:summary|content)[^>]*>(.*?)</(?:summary|content)>", b)
            p = FIELD_RE["date"].search(b)
            title = strip_tags(t.group(1)) if t else ""
            if len(title) < 8:
                continue
            items.append({
                "title": title,
                "summary": shorten(s.group(1)) if s else "",
                "source": source,
                "url": l.group(1) if l else "",
                "pub": parse_date(p.group(1)) if p else None,
            })
    return items[:40]


def parse_gov_list(html_text: str, source: str) -> list[dict]:
    """通用中文新闻列表页解析：抓取形如 <a href="...">标题</a> 的条目。

    适用于中国政府网「要闻 / 最新政策」、新华网时政等栏目页。
    只保留长度合理、链接像文章页的条目，尽量降低误抓导航文字的概率。
    """
    out, seen = [], set()
    for m in re.finditer(r'(?s)<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', html_text):
        href = m.group(1).strip()
        title = strip_tags(m.group(2))
        if not (12 <= len(title) <= 70):
            continue
        if any(b in title for b in BLACKLIST):
            continue
        if not re.search(r"(/\d{6,}|content_\d+|\.htm|\.shtml)", href):
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            base = re.match(r"(https?://[^/]+)", SOURCE_BASE.get(source, "") or "")
            href = (base.group(1) if base else "") + href
        k = norm_key(title)
        if k in seen:
            continue
        seen.add(k)
        out.append({"title": title, "summary": "", "source": source, "url": href, "pub": None})
        if len(out) >= 30:
            break
    return out


# 相对链接补全用的站点前缀
SOURCE_BASE = {
    "中国政府网": "https://www.gov.cn",
    "新华网": "https://www.news.cn",
    "最新政策": "https://www.gov.cn",
}


def parse_60s(js: str, source: str = "公开新闻快讯") -> list[dict]:
    """60 秒读懂世界等每日快讯 API（最后一个兜底源）。"""
    try:
        obj = json.loads(js)
    except Exception:  # noqa: BLE001
        return []
    data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
    news = data.get("news") or obj.get("news") or []
    out = []
    for n in news[:20]:
        line = strip_tags(str(n))
        if len(line) < 10:
            continue
        out.append({"title": line[:38] + ("…" if len(line) > 38 else ""),
                    "summary": line, "source": source, "url": "", "pub": None})
    return out


def parse_cntv(js: str, source: str = "央视新闻") -> list[dict]:
    """央视网栏目 JSON 接口（新闻联播 / 新闻直播间）。

    当前 SOURCES 未启用（实测该接口已改版返回空），保留此解析器以便
    你日后找到可用的栏目接口时直接换上。
    """
    try:
        obj = json.loads(js)
    except Exception:  # noqa: BLE001
        return []
    data = obj.get("data") or {}
    arr = data.get("list") or data.get("response") or []
    out = []
    for it in arr[:20]:
        title = strip_tags(str(it.get("title") or ""))
        if len(title) < 8:
            continue
        out.append({"title": title, "summary": "", "source": source,
                    "url": str(it.get("url") or it.get("h5_url") or ""), "pub": None})
    return out


SOURCE_BASE = {
    "中国政府网": "https://www.gov.cn",
    "新华网": "https://www.news.cn",
    "最新政策": "https://www.gov.cn",
}

# 数据源清单：(名称, 地址, 解析函数, 权重)  权重越小越优先
#
# 排序依据来自 `--source-check` 的实测结果（2026-09-10 体检）：
#   · 中新网滚动新闻 RSS —— 唯一确认「带时间戳且当日更新」的源，设为一级源
#   · 中国政府网要闻 / 最新政策 —— 最权威，但列表页在部分网络环境下会被拦成空页
#   · 新华网、央视新闻 —— 作为补充，条目普遍无时间戳，排序时自动靠后
#   · 每日快讯 —— 最后一个兜底，只在前面的源凑不满 10 条时才用
#   · 人民网 RSS —— 实测最新条目停留在 2025-06，已长期停更，故移除（见 README）
# 你可以随时运行 `python scripts/fetch_daily.py --source-check` 重新体检后调整本列表。
SOURCES = [
    ("中国新闻网", "https://www.chinanews.com.cn/rss/scroll-news.xml", parse_rss, 10),
    ("中新网·国内", "https://www.chinanews.com.cn/rss/china.xml", parse_rss, 12),
    ("中新网·要闻", "https://www.chinanews.com.cn/rss/importnews.xml", parse_rss, 14),
    ("中国政府网", "https://www.gov.cn/yaowen/liebiao/", parse_gov_list, 20),
    ("最新政策", "https://www.gov.cn/zhengce/zuixin/", parse_gov_list, 25),
    ("新华网", "https://www.news.cn/politics/news_politics.xml", parse_rss, 40),
    ("央视新闻", "https://news.cctv.com/", parse_gov_list, 50),
    ("每日快讯", "https://60s.viki.moe/v2/60s", parse_60s, 90),
]


def collect(offline: bool, limit: int, max_age_days: int = 3) -> tuple[list[dict], list[str]]:
    """按优先级汇总候选新闻，返回 (候选列表, 成功来源名)。"""
    cands: list[dict] = []
    used: list[str] = []
    if offline:
        return cands, used
    today = dt.datetime.now(BJT).date()
    for name, url, parser, weight in SOURCES:
        # 已有足够「带摘要且不过期」的候选就提前收工
        good = [c for c in cands
                if c.get("summary") and not (
                    c.get("pub") is not None and max_age_days > 0
                    and (today - c["pub"]).days > max_age_days)]
        if len(good) >= limit:
            break
        text = http_get(url)
        if not text or len(text) < 200:
            continue
        try:
            got = parser(text, name)
        except Exception as e:  # noqa: BLE001
            warn("%s 解析异常：%s" % (name, e))
            continue
        got = [g for g in got if g.get("title") and not any(b in g["title"] for b in BLACKLIST)]
        if not got:
            continue
        for g in got:
            g["_w"] = weight
        cands.extend(got)
        dated = [g["pub"] for g in got if g.get("pub")]
        extra = ""
        if dated:
            extra = "，最新 %s" % max(dated).isoformat()
        used.append(name)
        log("已从 %s 获取 %d 条候选%s" % (name, len(got), extra))
    return cands, used


def rank_and_pick(cands: list[dict], limit: int, max_age_days: int = 3,
                  today: dt.date | None = None, min_score: int | None = 4,
                  fill: bool = False) -> tuple[list[dict], int, int]:
    """按时政相关性 → 时间新鲜度 → 来源权重 → 摘要完整度排序，去重后取前 limit 条。

    返回 (选中列表, 因过旧被丢弃的条数, 因相关性不足被丢弃的条数)。
    若达标条目不足 limit，会自动逐级放宽阈值，保证尽量凑满十条。
    """
    today = today or dt.datetime.now(BJT).date()

    fresh, dropped = [], 0
    for c in cands:
        p = c.get("pub")
        if p is not None and max_age_days > 0 and (today - p).days > max_age_days:
            dropped += 1
            continue
        fresh.append(c)

    for c in fresh:
        c["_s"] = score_item(c["title"], c.get("summary", ""))

    def key(c):
        p = c.get("pub")
        age = (today - p).days if p is not None else 99   # 无时间戳的排在有时间戳的之后
        return (-c["_s"], age, c.get("_w", 99), 0 if c.get("summary") else 1)

    ranked = sorted(fresh, key=key)

    # 阈值逐级放宽：优先只保留高相关条目；若凑不满十条再依次放宽，
    # 在「宁缺毋滥」与「尽量凑满」之间取得平衡。
    # 注意每次都从完整的 ranked 里筛，避免逐级收窄后把条目越筛越少。
    floor = min_score if min_score is not None else 4
    ladder = (floor, 3, 2, 0, -999) if fill else (floor, 3, 2, 0)
    ordered = ranked
    for th in ladder:
        if th > floor:
            continue
        pool = [c for c in ranked if c["_s"] >= th]
        ordered = pool
        if len(pool) >= limit:
            break
    weak = sum(1 for c in fresh if c["_s"] < floor)

    seen, picked = set(), []
    for c in ordered:
        k = norm_key(c["title"])
        if not k or k in seen:
            continue
        seen.add(k)
        picked.append(c)
        if len(picked) >= limit:
            break
    return picked, dropped, weak


def source_check() -> int:
    """诊断：逐个探测来源是否可用、是否带时间戳、内容是否新鲜。"""
    log("开始来源体检（各源逐一探测，可能需要 1 分钟）…")
    print("")
    print("%-12s %-8s %-8s %-10s %s" % ("来源", "状态", "候选数", "带时间戳", "最新条目日期"))
    print("-" * 74)
    today = dt.datetime.now(BJT).date()
    for name, url, parser, weight in SOURCES:
        text = http_get(url, retries=0)
        if not text:
            print("%-12s %-8s %-8s %-10s %s" % (name, "不可用", "-", "-", "-"))
            continue
        if len(text) < 200:
            print("%-12s %-8s %-8s %-10s %s"
                  % (name, "空响应", "-", "-", "可能被反爬拦截，或该地址已失效"))
            continue
        try:
            got = parser(text, name)
        except Exception as e:  # noqa: BLE001
            print("%-12s %-8s %s" % (name, "解析失败", e))
            continue
        dated = [g["pub"] for g in got if g.get("pub")]
        newest = max(dated).isoformat() if dated else "（无时间戳）"
        age = "｜注意：内容已过期" if dated and (today - max(dated)).days > 3 else ""
        print("%-12s %-8s %-8d %-10d %s%s"
              % (name, "可用", len(got), len(dated), newest, age))
    print("")
    log("建议：把体检结果中「不可用」或「内容已过期」的源从 SOURCES 中移除，")
    log("      并在 data/manual/<日期>.json 中人工补录，以保证内容准确。")
    return 0


def load_manual(date_str: str) -> list[dict]:
    p = os.path.join(MANUAL, date_str + ".json")
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            obj = json.load(f)
        arr = obj if isinstance(obj, list) else obj.get("news", [])
        out = []
        for n in arr:
            if not n.get("title"):
                continue
            out.append({
                "title": str(n["title"]).strip(),
                "summary": shorten(str(n.get("summary", ""))),
                "source": str(n.get("source", "人工补录")).strip(),
                "url": str(n.get("url", "")).strip(),
                "tag": str(n.get("tag", "")).strip(),
            })
        log("人工补录文件提供 %d 条" % len(out))
        return out
    except Exception as e:  # noqa: BLE001
        warn("人工补录文件解析失败：%s" % e)
        return []


# ---------------------------------------------------------------- 输出

def js_string(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def write_day(date_str: str, news: list[dict], sources: list[str]) -> str:
    path = os.path.join(DATA, date_str + ".js")
    gen = dt.datetime.now(BJT).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    lines = [
        "/* %s 时政要闻 · 自动抓取 + 人工校核" % date_str,
        " * 来源：%s" % ("、".join(sources) if sources else "人工补录"),
        " * 本文件由 scripts/fetch_daily.py 自动生成，请勿手工编辑；",
        " *   需要修改内容请改用 data/manual/%s.json 后重新运行脚本。" % date_str,
        " */",
        "window.__DAILY__ = window.__DAILY__ || {};",
        'window.__DAILY__["%s"] = {' % date_str,
        '  date: %s,' % js_string(date_str),
        '  generated: %s,' % js_string(gen),
        '  source: %s,' % js_string(" / ".join(sources) if sources else "人工补录"),
        "  digest: %s," % js_string("；".join(n["title"][:22] for n in news[:3])),
        "  news: [",
    ]
    for i, n in enumerate(news):
        lines += [
            "    {",
            "      title: %s," % js_string(n["title"]),
            "      summary: %s," % js_string(n.get("summary") or n["title"]),
            "      source: %s," % js_string(n.get("source", "—")),
            "      tag: %s," % js_string(n.get("tag") or make_tag(n["title"] + n.get("summary", ""))),
            "      url: %s" % js_string(n.get("url", "")),
            "    }" + ("," if i < len(news) - 1 else ""),
        ]
    lines += ["  ]", "};", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def write_manifest() -> list[str]:
    dates = sorted(
        (f[:-3] for f in os.listdir(DATA)
         if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.js", f)),
        reverse=True,
    )
    today = dt.datetime.now(BJT).strftime("%Y-%m-%d")
    body = "\n".join([
        "/* 可用日期清单 · 由 scripts/fetch_daily.py 自动生成 */",
        "window.__DATA_INDEX__ = {",
        '  updated: %s,' % js_string(today),
        "  dates: [" + ", ".join(js_string(d) for d in dates) + "]",
        "};",
        "",
    ])
    with open(os.path.join(DATA, "manifest.js"), "w", encoding="utf-8") as f:
        f.write(body)
    return dates


# ---------------------------------------------------------------- 自检

def selftest() -> int:
    """不联网，用内置样例验证解析器与打标逻辑。"""
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(("  ok  " if cond else "  FAIL ") + name)
        if not cond:
            fails += 1

    print("解析器自检")
    rss = """<?xml version="1.0"?><rss><channel>
      <item><title><![CDATA[习近平向全国广大教师和教育工作者致以节日祝贺]]></title>
      <link>https://www.gov.cn/a.htm</link>
      <pubDate>Tue, 09 Sep 2026 10:00:00 GMT</pubDate>
      <description><![CDATA[<p>在第四十二个教师节到来之际，习近平代表党中央致以节日祝贺。</p>]]></description></item>
      <item><title>短</title><link>x</link><description>y</description></item>
    </channel></rss>"""
    r = parse_rss(rss, "人民网")
    check("RSS 解析出 1 条（过滤过短标题）", len(r) == 1)
    check("RSS 标题去 CDATA 与标签", r[0]["title"].startswith("习近平向全国"))
    check("RSS 摘要剥掉 HTML 标签", "<p>" not in r[0]["summary"] and "第四十二个教师节" in r[0]["summary"])
    check("RSS 链接正确", r[0]["url"] == "https://www.gov.cn/a.htm")
    check("RSS 解析出发布时间", r[0]["pub"] == dt.date(2026, 9, 9))

    check("日期解析：ISO 格式", parse_date("2026-09-09T08:00:00+08:00") == dt.date(2026, 9, 9))
    check("日期解析：RFC822 格式", parse_date("Tue, 09 Sep 2026 10:00:00 GMT") == dt.date(2026, 9, 9))
    check("日期解析：无效串返回 None", parse_date("昨天") is None)

    gov = """<ul><li><a href="/yaowen/liebiao/202609/content_1234567.htm">国务院任免国家工作人员：任命秦运彪为公安部副部长</a></li>
      <li><a href="更多">更多</a></li>
      <li><a href="/about.htm">关于我们</a></li></ul>"""
    g = parse_gov_list(gov, "中国政府网")
    check("列表页只抓文章型链接（滤掉导航）", len(g) == 1)
    check("相对链接补全为绝对地址", g[0]["url"].startswith("https://www.gov.cn/yaowen/"))

    js = json.dumps({"data": {"news": ["8月份CPI同比上涨0.8%，核心CPI涨幅回升至1.0%", "短"]}}, ensure_ascii=False)
    s = parse_60s(js)
    check("快讯 JSON 解析出 1 条", len(s) == 1)

    print("打标自检")
    check("CPI 归入经济数据", make_tag("8月份CPI同比上涨0.8%") == "经济数据")
    check("医保归入民生保障", make_tag("长护险2028年底全国基本覆盖，医保报销范围扩大") == "民生保障")
    check("条例归入法治建设", make_tag("李强签署国务院令 公布修订后的条例") == "法治建设")
    check("领导人纯国内活动不误判为外交", make_tag("习近平签署命令 发布军事设施建设条例") == "法治建设")
    check("真正的外事活动归入国际外交", make_tag("习近平同英国首相通电话") == "国际外交")
    check("默认回落到时政要闻", make_tag("某地举办文化活动") == DEFAULT_TAG)

    print("去重排序与时效自检")
    today = dt.date(2026, 9, 10)
    fresh = [{"title": "习近平同英国首相通电话", "_w": 30, "summary": "", "pub": dt.date(2026, 9, 9)},
             {"title": "习近平同英国首相通电话！", "_w": 10, "summary": "有摘要", "pub": dt.date(2026, 9, 9)},
             {"title": "国家税务总局发布新公告", "_w": 20, "summary": "x", "pub": dt.date(2026, 9, 9)}]
    p, dropped, weak = rank_and_pick(fresh, 10, 3, today, 0)
    check("标题去重后仅 2 条", len(p) == 2)
    check("同标题保留高优先级来源", p[0]["_w"] == 10)
    check("全部新鲜时不丢弃任何条目", dropped == 0)

    stale = fresh + [{"title": "上个月的旧闻标题足够长", "_w": 10, "summary": "x", "pub": dt.date(2026, 9, 1)}]
    p1, d1, _w1 = rank_and_pick(stale, 10, 3, today, 0)
    check("超过 3 天的旧闻被丢弃", d1 == 1 and all("上个月" not in x["title"] for x in p1))
    p2, d2, _w2 = rank_and_pick(stale, 10, 0, today, -999)
    check("--max-age-days 0 时不丢弃", d2 == 0 and len(p2) == 3)

    p3, _a, _b = rank_and_pick(
        [{"title": "无时间戳的条目", "_w": 5, "summary": "s", "pub": None},
         {"title": "有时间戳的新条目", "_w": 99, "summary": "s", "pub": today}], 2, 3, today, -999)
    check("有时间戳的条目优先于无时间戳的", p3[0]["title"] == "有时间戳的新条目")
    p4, _a2, _b2 = rank_and_pick([{"title": "标题太短但也算", "_w": 5, "summary": "s", "pub": None}], 10, 3, today, -999)
    check("无时间戳的条目不会被误删", len(p4) == 1)

    print("时政相关性打分自检")
    check("领导人活动得高分", score_item("习近平向全国广大教师和教育工作者致以节日祝贺") >= 3)
    check("国务院政策得高分", score_item("国务院印发《关于开展第四次全国农业普查的通知》") >= 5)
    check("经济数据得高分", score_item("8月份CPI同比上涨0.8%，核心CPI涨幅回升至1.0%") >= 2)
    check("非遗手作被扣分", score_item("麦秆剪贴技艺省级代表性传承人李宝霞：赋予方寸麦秆万千气象") <= 0)
    check("风光图片新闻被扣分", score_item("广西三江侗乡：梯田染金入画来") <= 0)
    check("展会花絮被扣分", score_item("浙江杭州：“AI Show”引人关注") <= 0)
    check("健康养生类被扣分", score_item("秋燥分两种，很多人都补反了，越补燥感越重！") <= 0)
    check("生活消费类被扣分", score_item("大学生活费怎么给？谈“钱”之前，先谈“生活”") <= 0)
    mixed = [{"title": "习近平同英国首相通电话", "_w": 30, "summary": "", "pub": today},
             {"title": "广西三江侗乡：梯田染金入画来", "_w": 10, "summary": "", "pub": today}]
    pm, _x, _y = rank_and_pick(mixed, 1, 3, today, 4)
    check("打分能在同为『今日』的条目中把时政排在图片新闻之前",
          len(pm) == 1 and pm[0]["title"].startswith("习近平"))

    print("截断自检")
    long_txt = "这是第一句。" * 40
    check("超长摘要被截断且在句号处收口", len(shorten(long_txt, 100)) <= 102)

    print("\n自检结果：%s" % ("全部通过 ✅" if fails == 0 else "失败 %d 项 ❌" % fails))
    return 0 if fails == 0 else 1


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="公考日报时政抓取")
    ap.add_argument("--date", default=None, help="目标日期 YYYY-MM-DD，默认北京时间今天")
    ap.add_argument("--offline", action="store_true", help="不联网，仅用人工补录文件")
    ap.add_argument("--selftest", action="store_true", help="跑解析器自检")
    ap.add_argument("--source-check", action="store_true", dest="source_check",
                    help="体检各新闻源的可用性与内容新鲜度")
    ap.add_argument("--max-age-days", type=int, default=3, dest="max_age",
                    help="丢弃发布时间早于 N 天的条目（0=不限制），默认 3")
    ap.add_argument("--min-score", type=int, default=4, dest="min_score",
                    help="时政相关性最低分（-999=不筛选），默认 4；调低会纳入更多边缘新闻")
    ap.add_argument("--fill", action="store_true",
                    help="凑不满十条时也强行用相关性为负的内容填满（默认不填，宁缺毋滥）")
    ap.add_argument("--keep-days", type=int, default=0, help="仅保留最近 N 天数据文件（0=不清理）")
    ap.add_argument("--skip-if-fresh", action="store_true", dest="skip_fresh",
                    help="当天目标文件已存在且已满 10 条时直接跳过（用于兜底重试，避免重复抓取）")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.source_check:
        return source_check()

    date_str = args.date or dt.datetime.now(BJT).strftime("%Y-%m-%d")
    log("目标日期：%s（北京时间）" % date_str)

    if args.skip_fresh:
        existing = os.path.join(DATA, date_str + ".js")
        if os.path.exists(existing):
            with open(existing, "r", encoding="utf-8") as f:
                n = f.read().count("    title:")
            if n >= PER_DAY:
                log("本期已存在且已满 %d 条，跳过抓取（--skip-if-fresh）。" % n)
                return 0
            log("本期仅 %d 条，执行补抓。" % n)

    news: list[dict] = []

    # 1) 人工补录优先
    for n in load_manual(date_str):
        if not n.get("tag"):
            n["tag"] = make_tag(n["title"] + n["summary"])
        news.append(n)

    # 2) 自动抓取补齐
    sources = ["人工补录"] if news else []
    if len(news) < PER_DAY:
        cands, used = collect(args.offline, PER_DAY, args.max_age)
        picked, dropped, weak = rank_and_pick(
            cands, PER_DAY, args.max_age, None, args.min_score, args.fill)
        sources += used
        if dropped:
            warn("已丢弃 %d 条超出 %d 天的旧闻（用 --max-age-days 0 可关闭）"
                 % (dropped, args.max_age))
        if weak:
            warn("有 %d 条候选因「时政相关性」偏低被降权（用 --min-score -999 可关闭）" % weak)
        for c in picked:
            if len(news) >= PER_DAY:
                break
            if any(norm_key(n["title"]) == norm_key(c["title"]) for n in news):
                continue
            news.append({
                "title": c["title"],
                "summary": c.get("summary") or c["title"],
                "source": c.get("source", "—"),
                "url": c.get("url", ""),
                "tag": make_tag(c["title"] + c.get("summary", "")),
            })

    if not news:
        warn("本次未抓到任何内容，且没有人工补录文件。")
        warn("为避免把站点上的上一期数据覆盖成空白，本次不做任何写入。")
        warn("请检查网络，或在 data/manual/%s.json 中手工补录后重跑。" % date_str)
        return 0

    if len(news) < PER_DAY:
        warn("仅取得 %d/%d 条 —— 当日候选里达到时政相关性门槛的内容不足。" % (len(news), PER_DAY))
        warn("这是有意为之的「宁缺毋滥」：宁可少发，也不拿社会新闻凑数。")
        warn("请在 data/manual/%s.json 中补足剩余条目，或用 --fill 放宽门槛。" % date_str)

    news = news[:PER_DAY]
    path = write_day(date_str, news, [s for s in sources if s])
    dates = write_manifest()

    if args.keep_days > 0:
        for d in dates[args.keep_days:]:
            try:
                os.remove(os.path.join(DATA, d + ".js"))
            except OSError:
                pass

    log("已写出 %s（%d 条）" % (os.path.relpath(path, ROOT), len(news)))
    log("已刷新 data/manifest.js，当前共 %d 期：%s" % (len(dates), ", ".join(dates[:5])))
    for i, n in enumerate(news, 1):
        log("  %2d. [%s] %s" % (i, n["tag"], n["title"][:44]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001  兜底：绝不让定时任务变红
        warn("未预期的异常：%r" % (exc,))
        warn("本次不写入数据，站点将保持上一期内容不变。")
        sys.exit(0)
