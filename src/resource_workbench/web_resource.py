from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat


HTTP_TIMEOUT_SECONDS = 18
MAX_HTML_BYTES = 900_000
MAX_IMAGE_BYTES = 8_000_000
SCREENSHOT_TIMEOUT_MS = 34_000
SCREENSHOT_POLL_MS = 1_800
SCREENSHOT_MIN_TEXT_WAIT_MS = 8_000
SCREENSHOT_VERIFICATION_GRACE_MS = 18_000
SCREENSHOT_SIZE = (1280, 800)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.in_jsonld = False
        self.title_parts: list[str] = []
        self.jsonld_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.links: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        attrs_dict = {str(key).lower(): str(value or "") for key, value in attrs}
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
            return
        if tag == "script" and "ld+json" in attrs_dict.get("type", "").lower():
            self.in_jsonld = True
            return
        if tag == "meta":
            key = (attrs_dict.get("property") or attrs_dict.get("name") or "").strip().lower()
            content = attrs_dict.get("content", "").strip()
            if key and content:
                self.meta[key] = content
            return
        if tag == "link":
            rel = attrs_dict.get("rel", "").strip().lower()
            href = attrs_dict.get("href", "").strip()
            if rel and href:
                self.links[rel] = href

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False
        if tag.lower() == "script":
            self.in_jsonld = False

    def handle_data(self, data: str) -> None:
        if self.in_title and data:
            self.title_parts.append(data)
        elif self.in_jsonld and data:
            self.jsonld_parts.append(data)


def normalise_url(text: str) -> str:
    url = str(text or "").strip()
    if not url:
        raise ValueError("链接为空。")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("只支持 http 或 https 网页链接。")
    return urllib.parse.urlunparse(parsed)


def is_web_card(card: dict) -> bool:
    return str(card.get("resource_kind") or "") == "web" or bool(card.get("source_url"))


def create_web_resource_card(url_text: str, cache_dir: Path) -> dict:
    url = normalise_url(url_text)
    metadata = fetch_web_metadata(url)
    preview_path = build_web_preview(metadata, cache_dir)
    domain = metadata.get("domain") or urllib.parse.urlparse(url).netloc
    title = metadata.get("title") or domain or url
    description = metadata.get("description") or ""
    content_kind = metadata.get("content_kind") or _infer_content_kind(title, description, url)
    content_label = _content_kind_label(content_kind)
    platform = metadata.get("platform") or _platform_name(domain)
    author = metadata.get("author") or ""
    tags = ["网页", content_label]
    if platform:
        tags.append(str(platform))
    elif domain:
        tags.append(str(domain))
    if author:
        tags.append(f"作者:{author}")
    suggested_type = "tutorial" if _looks_like_learning_page(title, description, url) else "photo" if content_kind == "photo" else "unknown"
    return {
        "resource_kind": "web",
        "name": title,
        "display_name": title,
        "source_url": url,
        "web_domain": domain,
        "web_title": title,
        "web_description": description,
        "web_content_kind": content_kind,
        "web_content_label": content_label,
        "web_platform": platform,
        "web_author": author,
        "web_image_url": metadata.get("image_url") or "",
        "suggested_type": suggested_type,
        "confidence": "high" if metadata.get("rich") else "medium" if description else "low",
        "content_tags": tags,
        "target_suggestions": [],
        "target_path_hints": [],
        "needs_human_review": True,
        "archive_count": 0,
        "source_archive_count": 0,
        "source_archives": [],
        "inspected_archives": 0,
        "virtual_archive_count": 0,
        "total_files": 1,
        "total_dirs": 0,
        "total_bytes": 0,
        "buckets": {"web": 1},
        "extension_counts": {},
        "archive_virtual_buckets": {},
        "archive_entry_samples": [],
        "preview_source": {"kind": "file", "path": str(preview_path)} if preview_path else None,
        "reasons": _web_reasons(metadata),
    }


def fetch_web_metadata(url: str) -> dict:
    request = urllib.request.Request(url, headers=_browser_headers(url))
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_HTML_BYTES)
            final_url = response.geturl() or url
            content_type = response.headers.get("content-type", "")
    except (urllib.error.URLError, OSError) as exc:
        parsed = urllib.parse.urlparse(url)
        platform = _platform_name(parsed.netloc)
        kind = _infer_content_kind("", "", url)
        platform_data = _platform_metadata(url, "")
        if platform_data and platform_data.get("rich"):
            platform_data.setdefault("ok", True)
            platform_data.setdefault("url", url)
            platform_data.setdefault("final_url", url)
            platform_data.setdefault("domain", parsed.netloc)
            platform_data.setdefault("platform", platform)
            platform_data.setdefault("content_kind", kind)
            platform_data.setdefault("error", str(exc))
            return platform_data
        return {
            "ok": False,
            "url": url,
            "final_url": url,
            "domain": parsed.netloc,
            "title": _title_from_url_slug(url) or platform or parsed.netloc or url,
            "description": _blocked_description(platform, kind, exc),
            "image_url": _site_icon_url(parsed.netloc),
            "image_is_fallback": True,
            "screenshot_preferred": True,
            "platform": platform,
            "content_kind": kind,
            "rich": bool(platform),
            "error": str(exc),
        }

    charset = _charset_from_content_type(content_type) or "utf-8"
    html = _decode_html(raw, charset)
    parser = _MetadataParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    parsed_final = urllib.parse.urlparse(final_url)
    platform_data = _platform_metadata(final_url, html)
    if platform_data:
        platform_data.setdefault("ok", True)
        platform_data.setdefault("url", url)
        platform_data.setdefault("final_url", final_url)
        platform_data.setdefault("domain", parsed_final.netloc)
        platform_data.setdefault("platform", _platform_name(parsed_final.netloc))
        platform_data.setdefault("content_type", content_type)
        return platform_data

    jsonld = _jsonld_metadata(parser.jsonld_parts)
    title = _first_text(
        parser.meta.get("og:title"),
        parser.meta.get("twitter:title"),
        jsonld.get("title"),
        " ".join(parser.title_parts),
        _platform_name(parsed_final.netloc),
        parsed_final.netloc,
    )
    description = _first_text(
        parser.meta.get("og:description"),
        parser.meta.get("twitter:description"),
        parser.meta.get("description"),
        jsonld.get("description"),
    )
    image = _first_text(
        parser.meta.get("og:image"),
        parser.meta.get("twitter:image"),
        jsonld.get("image"),
        parser.links.get("image_src"),
    )
    image_is_fallback = False
    if not image:
        image = _first_text(parser.links.get("shortcut icon"), parser.links.get("icon"))
        image_is_fallback = bool(image)
    image_url = urllib.parse.urljoin(final_url, image) if image else ""
    platform = _platform_name(parsed_final.netloc)
    content_kind = _infer_content_kind(title, description, final_url, parser.meta, jsonld)
    if _looks_like_domain_title(title, parsed_final.netloc) or (platform and title.strip().lower() == platform.lower()):
        title = _title_from_url_slug(final_url) or platform or title
    if platform and not description:
        description = _platform_default_description(platform, final_url)
    return {
        "ok": True,
        "url": url,
        "final_url": final_url,
        "domain": parsed_final.netloc,
        "title": title,
        "description": description,
        "image_url": image_url or (_site_icon_url(parsed_final.netloc) if platform else ""),
        "image_is_fallback": image_is_fallback or (not image_url and bool(platform)),
        "screenshot_preferred": image_is_fallback or not image_url,
        "content_type": content_type,
        "platform": platform,
        "author": jsonld.get("author") or parser.meta.get("article:author") or "",
        "content_kind": content_kind,
        "rich": bool(title and title != parsed_final.netloc and (description or image_url or jsonld)),
    }


def _browser_headers(url: str = "") -> dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    }
    if url:
        headers["Referer"] = url
    return headers


def _platform_metadata(url: str, html: str) -> dict | None:
    parsed = urllib.parse.urlparse(url)
    domain = _domain_no_www(parsed.netloc)
    if domain.endswith("bilibili.com") or domain == "b23.tv":
        return _bilibili_metadata(url, html)
    return None


def _bilibili_metadata(url: str, html: str) -> dict:
    bvid = _bilibili_bvid(url, html)
    if bvid:
        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={urllib.parse.quote(bvid)}"
        try:
            request = urllib.request.Request(api_url, headers=_browser_headers(url))
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            data = payload.get("data") or {}
            if payload.get("code") == 0 and data:
                owner = data.get("owner") or {}
                stat = data.get("stat") or {}
                title = _first_text(data.get("title"), bvid)
                desc = _first_text(data.get("desc"))
                author = _first_text(owner.get("name"))
                parts = [
                    f"UP主：{author}" if author else "",
                    f"分区：{_first_text(data.get('tname'))}" if data.get("tname") else "",
                    f"播放：{stat.get('view')}" if stat.get("view") is not None else "",
                    desc,
                ]
                return {
                    "title": title,
                    "description": "；".join(part for part in parts if part),
                    "image_url": _https_url(_first_text(data.get("pic"))),
                    "platform": "Bilibili",
                    "author": author,
                    "content_kind": "video",
                    "rich": True,
                }
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass

    title = _first_text(_regex_first(html, r"<title[^>]*>(.*?)</title>"), "Bilibili")
    return {
        "title": _clean_bilibili_title(title),
        "description": "Bilibili 视频平台页面。若是具体视频链接，软件会尽量读取标题、封面、UP 主和分区。",
        "image_url": "",
        "platform": "Bilibili",
        "content_kind": "video_platform",
        "rich": True,
    }


def _bilibili_bvid(url: str, html: str) -> str:
    match = re.search(r"\b(BV[0-9A-Za-z]{10,})\b", url or "")
    if match:
        return match.group(1)
    return ""


def _clean_bilibili_title(title: str) -> str:
    title = re.sub(r"[_\- ]*哔哩哔哩.*$", "", title or "", flags=re.IGNORECASE).strip()
    return title or "Bilibili"


def _jsonld_metadata(jsonld_parts: list[str]) -> dict:
    merged: dict[str, str] = {}
    for raw in jsonld_parts:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for item in _jsonld_items(payload):
            if not isinstance(item, dict):
                continue
            title = _first_text(item.get("headline"), item.get("name"), item.get("title"))
            description = _first_text(item.get("description"), item.get("abstract"))
            image = _jsonld_image(item.get("image") or item.get("thumbnailUrl"))
            author = _jsonld_author(item.get("author") or item.get("creator"))
            if title and "title" not in merged:
                merged["title"] = title
            if description and "description" not in merged:
                merged["description"] = description
            if image and "image" not in merged:
                merged["image"] = image
            if author and "author" not in merged:
                merged["author"] = author
    return merged


def _jsonld_items(payload) -> list:  # noqa: ANN001
    if isinstance(payload, list):
        items = []
        for item in payload:
            items.extend(_jsonld_items(item))
        return items
    if isinstance(payload, dict):
        graph = payload.get("@graph")
        return [payload] + (_jsonld_items(graph) if graph else [])
    return []


def _jsonld_image(value) -> str:  # noqa: ANN001
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return _jsonld_image(value[0])
    if isinstance(value, dict):
        return _first_text(value.get("url"), value.get("contentUrl"))
    return ""


def _jsonld_author(value) -> str:  # noqa: ANN001
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return _jsonld_author(value[0])
    if isinstance(value, dict):
        return _first_text(value.get("name"), value.get("alternateName"))
    return ""


def _platform_name(domain: str) -> str:
    domain = _domain_no_www(domain)
    rules = [
        ("vintag.es", "Vintage Everyday"),
        ("skyscrapercity.com", "SkyscraperCity"),
        ("soviet-art.ru", "Soviet Art"),
        ("istockphoto.com", "iStock"),
        ("lensculture.com", "LensCulture"),
        ("mixamo.com", "Adobe Mixamo"),
        ("shotdeck.com", "ShotDeck"),
        ("budeco.top", "Budeco"),
        ("superhivemarket.com", "Superhive Market"),
        ("bilibili.com", "Bilibili"),
        ("b23.tv", "Bilibili"),
        ("youtube.com", "YouTube"),
        ("youtu.be", "YouTube"),
        ("instagram.com", "Instagram"),
        ("weibo.com", "微博"),
        ("xiaohongshu.com", "小红书"),
        ("xhslink.com", "小红书"),
        ("zhihu.com", "知乎"),
        ("artstation.com", "ArtStation"),
        ("behance.net", "Behance"),
        ("pinterest.", "Pinterest"),
        ("twitter.com", "X/Twitter"),
        ("x.com", "X/Twitter"),
        ("douyin.com", "抖音"),
        ("vimeo.com", "Vimeo"),
    ]
    for needle, name in rules:
        if needle in domain:
            return name
    return ""


def _domain_no_www(domain: str) -> str:
    domain = (domain or "").lower().split(":")[0]
    return domain[4:] if domain.startswith("www.") else domain


def _platform_default_title(platform: str, domain: str, url: str) -> str:
    slug_title = _title_from_url_slug(url)
    if slug_title:
        return slug_title
    kind = _content_kind_label(_infer_content_kind("", "", url))
    return f"{platform} {kind}" if kind != "网页" else platform or domain


def _platform_default_description(platform: str, url: str) -> str:
    kind = _content_kind_label(_infer_content_kind("", "", url))
    return _blocked_description(platform, _infer_content_kind("", "", url), None)


def _site_icon_url(domain: str) -> str:
    domain = _domain_no_www(domain)
    if not domain:
        return ""
    if "shotdeck.com" in domain:
        return "https://shotdeck.com/favicon.png"
    if "superhivemarket.com" in domain:
        return "https://www.google.com/s2/favicons?domain=superhivemarket.com&sz=256"
    if "mixamo.com" in domain:
        return "https://www.mixamo.com/favicon.ico"
    return f"https://{domain}/favicon.ico"


def _https_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def _blocked_description(platform: str, kind: str, exc: Exception | None) -> str:
    label = _content_kind_label(kind)
    base = f"{platform or '该站点'} 链接，内容类型判断为：{label}。"
    if exc is not None:
        base += f" 页面公开读取受限：{exc}"
    return base


def _infer_content_kind(
    title: str,
    description: str,
    url: str,
    meta: dict | None = None,
    jsonld: dict | None = None,
) -> str:
    text = f"{title} {description} {url}".lower()
    meta = meta or {}
    jsonld = jsonld or {}
    og_type = str(meta.get("og:type") or "").lower()
    domain = _domain_no_www(urllib.parse.urlparse(url).netloc)
    path = urllib.parse.urlparse(url).path.lower()
    if "superhivemarket.com" in domain or "blendermarket.com" in domain:
        return "product"
    if "mixamo.com" in domain:
        return "tool"
    if "shotdeck.com" in domain:
        return "reference"
    if "budeco.top" in domain:
        return "asset_marketplace"
    if "istockphoto.com" in domain:
        return "stock_photo"
    if "lensculture.com" in domain:
        return "photo_project"
    if "vintag.es" in domain:
        return "photo"
    if "skyscrapercity.com" in domain or "/threads/" in path:
        return "forum"
    if "video" in og_type or any(token in text for token in ("/video/", "bilibili.com/video", "youtube.com/watch", "youtu.be/", "vimeo.com")):
        return "video"
    if "article" in og_type or any(token in text for token in ("article", "blog", "post", "news", "专栏", "文章", "教程")):
        return "article"
    if "forum" in text or "thread" in text or "topic" in text or "帖子" in text:
        return "forum"
    if "image" in og_type or any(token in text for token in ("photo", "image", "gallery", "instagram.com", "pinterest", "照片", "图片", "图集")):
        return "photo"
    if "profile" in og_type or any(token in text for token in ("weibo.com", "twitter.com", "x.com", "xiaohongshu.com")):
        return "social"
    if jsonld.get("title") or jsonld.get("description"):
        return "article"
    if any(needle in domain for needle in ("bilibili.com", "youtube.com", "youtu.be", "douyin.com")):
        return "video_platform"
    return "webpage"


def _content_kind_label(kind: str) -> str:
    labels = {
        "video": "视频",
        "video_platform": "视频平台",
        "article": "文章",
        "forum": "论坛/帖子",
        "photo": "照片/图集",
        "stock_photo": "图库/素材",
        "photo_project": "摄影项目",
        "social": "社交动态",
        "tool": "工具",
        "reference": "参考库",
        "asset_marketplace": "资源站",
        "product": "产品/插件",
        "webpage": "网页",
    }
    return labels.get(str(kind or ""), "网页")


def _looks_like_domain_title(title: str, domain: str) -> bool:
    clean_title = _domain_no_www(str(title or "").strip())
    clean_domain = _domain_no_www(domain)
    return bool(clean_title and clean_domain and clean_title in {clean_domain, "www." + clean_domain})


def _title_from_url_slug(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    parts = [part for part in parsed.path.split("/") if part and not part.lower().startswith("page-")]
    if not parts:
        return ""
    if [part.lower() for part in parts[-2:]] == ["welcome", "login"]:
        return ""
    slug = parts[-1]
    if "." in slug:
        slug = slug.rsplit(".", 1)[0]
    if slug.lower() in {"login", "welcome", "search", "more-like-this", "products", "threads", "projects"} and len(parts) >= 2:
        slug = parts[-2]
    if slug.isdigit() and len(parts) >= 2:
        slug = parts[-2]
    slug = urllib.parse.unquote(slug)
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()
    if not slug:
        return ""
    words = []
    small = {"of", "the", "and", "or", "in", "on", "for", "to", "a", "an"}
    for index, word in enumerate(slug.split()):
        if index > 0 and word.lower() in small:
            words.append(word.lower())
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)


def _regex_first(text: str, pattern: str) -> str:
    match = re.search(pattern, text or "", re.IGNORECASE | re.DOTALL)
    return unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip() if match else ""


def build_web_preview(metadata: dict, cache_dir: Path) -> Path | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    url = str(metadata.get("final_url") or metadata.get("url") or "")
    title = str(metadata.get("title") or metadata.get("domain") or "Web Resource")
    domain = str(metadata.get("domain") or urllib.parse.urlparse(url).netloc or "")
    platform = str(metadata.get("platform") or _platform_name(domain) or domain)
    kind_label = _content_kind_label(str(metadata.get("content_kind") or _infer_content_kind(title, "", url)))
    author = str(metadata.get("author") or "")
    description = str(metadata.get("description") or "")
    key_basis = "|".join(
        str(part)
        for part in (
            url,
            title,
            metadata.get("image_url") or "",
            metadata.get("content_kind") or "",
            "screenshot-v3" if metadata.get("screenshot_preferred") or metadata.get("image_is_fallback") else "image-v2",
            author,
        )
    )
    key = hashlib.sha1(key_basis.encode("utf-8", errors="ignore")).hexdigest()[:24]
    final_path = cache_dir / f"web_{key}.png"
    if final_path.exists():
        return final_path

    image_path: Path | None = None
    used_screenshot = False
    if _should_capture_page_screenshot(metadata):
        image_path = _capture_webpage_screenshot(url, cache_dir / f"web_{key}_page.png")
        used_screenshot = bool(image_path)
    if not image_path and not metadata.get("image_is_fallback"):
        image_path = _download_image(metadata.get("image_url") or "", cache_dir / f"web_{key}_source")

    canvas = Image.new("RGB", (900, 560), _domain_color(domain))
    draw = ImageDraw.Draw(canvas)
    if image_path:
        try:
            with Image.open(image_path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((900, 560), Image.Resampling.LANCZOS)
                x = (900 - image.width) // 2
                y = (560 - image.height) // 2
                canvas.paste(image, (x, y))
        except Exception:
            pass
    else:
        _draw_generated_web_art(canvas, domain, platform, kind_label)
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle((0, 330, 900, 560), fill=(12, 18, 28, 212))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas)
    title_font = _font(34, bold=True)
    body_font = _font(20)
    small_font = _font(18)
    header = " · ".join(part for part in (platform, kind_label, author) if part)
    draw.text((34, 28), header[:90], fill=(255, 255, 255), font=small_font)
    y = 356
    for line in _wrap_text(title, title_font, 760, 2):
        draw.text((34, y), line, fill=(255, 255, 255), font=title_font)
        y += 42
    preview_description = _preview_description_for_card(description, kind_label, used_screenshot, bool(metadata.get("error")))
    if preview_description:
        y += 6
        for line in _wrap_text(preview_description, body_font, 810, 2):
            draw.text((34, y), line, fill=(220, 231, 243), font=body_font)
            y += 28
    canvas.save(final_path, "PNG")
    if image_path:
        image_path.unlink(missing_ok=True)
    return final_path


def _preview_description_for_card(description: str, kind_label: str, used_screenshot: bool, had_fetch_error: bool) -> str:
    if used_screenshot and had_fetch_error:
        return f"已生成网页预览；内容类型：{kind_label}。点击打开按钮可访问原网页。"
    if had_fetch_error:
        return f"站点可能需要登录或安全验证；内容类型：{kind_label}。点击打开按钮访问原网页。"
    return description


def _should_capture_page_screenshot(metadata: dict) -> bool:
    url = str(metadata.get("final_url") or metadata.get("url") or "")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    return bool(metadata.get("screenshot_preferred") or metadata.get("image_is_fallback") or not metadata.get("image_url"))


def _capture_webpage_screenshot(url: str, output_path: Path) -> Path | None:
    # Prefer a genuinely headless browser. It works safely from the analysis
    # worker thread and never opens a console or steals keyboard/mouse focus.
    headless_path = _capture_with_headless_browser(url, output_path)
    if headless_path:
        return headless_path
    try:
        from PySide6.QtCore import QEventLoop, QThread, QTimer, QUrl, Qt
        from PySide6.QtWidgets import QApplication
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except Exception:
        return None

    app = QApplication.instance()
    if app is None:
        return None
    # Qt WebEngine widgets may only be constructed on the GUI thread. A web
    # card created by AnalyzeWorker should fall back to generated artwork when
    # no external headless browser is available instead of crashing Qt.
    if QThread.currentThread() != app.thread():
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    view = QWebEngineView()
    view.resize(*SCREENSHOT_SIZE)
    view.setWindowFlag(Qt.WindowType.Tool, True)
    view.move(-32000, -32000)
    loop = QEventLoop()
    state = {
        "done": False,
        "blocked": False,
        "started": time.monotonic(),
        "require_large_image": _screenshot_requires_large_image(url),
        "large_image_url": "",
    }

    def finish(blocked: bool = False, delay_ms: int = 900) -> None:
        if state["done"]:
            return
        state["done"] = True
        state["blocked"] = blocked or _is_blocked_page_title(view.title())
        QTimer.singleShot(80 if state["blocked"] else delay_ms, loop.quit)

    def on_title_changed(title: str) -> None:
        elapsed_ms = int((time.monotonic() - float(state["started"])) * 1000)
        if _is_blocked_page_title(title) and elapsed_ms >= SCREENSHOT_VERIFICATION_GRACE_MS:
            finish(True)

    def probe_page_ready() -> None:
        if state["done"]:
            return

        def handle_probe(payload) -> None:  # noqa: ANN001
            if state["done"]:
                return
            elapsed_ms = int((time.monotonic() - float(state["started"])) * 1000)
            data = _decode_screenshot_probe(payload)
            title = str(data.get("title") or view.title() or "")
            blocked_probe = _is_blocked_page_title(title) or _looks_like_verification_text(str(data.get("text") or ""))
            if blocked_probe and elapsed_ms >= SCREENSHOT_VERIFICATION_GRACE_MS:
                finish(True)
                return
            if data.get("large_image_ready"):
                state["large_image_url"] = str(data.get("large_image_url") or "")
                finish(False)
                return
            if (
                not state["require_large_image"]
                and elapsed_ms >= SCREENSHOT_MIN_TEXT_WAIT_MS
                and data.get("has_body_text")
                and data.get("ready_state") == "complete"
            ):
                finish(False)
                return
            QTimer.singleShot(SCREENSHOT_POLL_MS, probe_page_ready)

        try:
            view.page().runJavaScript(_SCREENSHOT_READY_SCRIPT, handle_probe)
        except RuntimeError:
            finish(False)

    view.titleChanged.connect(on_title_changed)
    view.loadFinished.connect(lambda _ok: QTimer.singleShot(SCREENSHOT_POLL_MS, probe_page_ready))
    QTimer.singleShot(2_500, probe_page_ready)
    QTimer.singleShot(SCREENSHOT_TIMEOUT_MS, finish)

    try:
        view.load(QUrl(url))
        view.show()
        loop.exec()
        app.processEvents()
        if state["blocked"]:
            return None
        large_image_url = str(state.get("large_image_url") or "")
        if large_image_url:
            image_path = _download_image(_https_url(large_image_url), output_path.with_name(f"{output_path.stem}_image"))
            if image_path:
                return image_path
        pixmap = view.grab()
        if pixmap.isNull() or pixmap.width() <= 10 or pixmap.height() <= 10:
            return None
        if not pixmap.save(str(output_path), "PNG"):
            return None
    finally:
        view.close()
        view.deleteLater()
        app.processEvents()

    if _is_unusable_screenshot(output_path):
        output_path.unlink(missing_ok=True)
        return None
    return output_path


def _capture_with_headless_browser(url: str, output_path: Path) -> Path | None:
    browser = _headless_browser_executable()
    if browser is None:
        return None
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="resource-workbench-web-") as profile:
            command = [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--no-first-run",
                "--no-default-browser-check",
                "--hide-scrollbars",
                "--dump-dom",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=12000",
                f"--user-data-dir={profile}",
                f"--window-size={SCREENSHOT_SIZE[0]},{SCREENSHOT_SIZE[1]}",
                f"--screenshot={output_path}",
                url,
            ]
            kwargs: dict = {
                "capture_output": True,
                "timeout": max(20, int(SCREENSHOT_TIMEOUT_MS / 1000) + 4),
                "check": False,
            }
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                kwargs["startupinfo"] = startupinfo
            completed = subprocess.run(command, **kwargs)
    except (OSError, subprocess.SubprocessError):
        output_path.unlink(missing_ok=True)
        return None
    process_text = "\n".join(
        _decode_process_text(part)
        for part in (getattr(completed, "stdout", b""), getattr(completed, "stderr", b""))
    )
    if _looks_like_verification_text(process_text):
        output_path.unlink(missing_ok=True)
        return None
    if not output_path.exists() or output_path.stat().st_size < 1_000:
        output_path.unlink(missing_ok=True)
        return None
    if _is_unusable_screenshot(output_path):
        output_path.unlink(missing_ok=True)
        return None
    return output_path


def _headless_browser_executable() -> Path | None:
    names = ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser")
    candidates: list[Path] = []
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            candidates.append(Path(resolved))
    if os.name == "nt":
        program_files = [
            os.environ.get("PROGRAMFILES", ""),
            os.environ.get("PROGRAMFILES(X86)", ""),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        suffixes = (
            Path("Microsoft/Edge/Application/msedge.exe"),
            Path("Google/Chrome/Application/chrome.exe"),
            Path("Chromium/Application/chrome.exe"),
        )
        for base in program_files:
            if not base:
                continue
            candidates.extend(Path(base) / suffix for suffix in suffixes)
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate
    return None


def _decode_process_text(value: bytes | str) -> str:
    if isinstance(value, str):
        return value
    for encoding in ("utf-8", "gb18030", "cp1252"):
        try:
            return bytes(value or b"").decode(encoding)
        except UnicodeDecodeError:
            continue
    return bytes(value or b"").decode("utf-8", errors="replace")


_SCREENSHOT_READY_SCRIPT = """
JSON.stringify((() => {
  const bodyText = document.body ? document.body.innerText.slice(0, 900) : "";
  const candidates = Array.from(document.images || []).map((img) => {
    const rect = img.getBoundingClientRect();
    const naturalArea = (img.naturalWidth || 0) * (img.naturalHeight || 0);
    const visibleArea = Math.max(0, rect.width || 0) * Math.max(0, rect.height || 0);
    return {
      complete: !!img.complete,
      natural_area: naturalArea,
      visible_area: visibleArea,
      src: img.currentSrc || img.src || ""
    };
  }).filter((item) => item.complete && item.natural_area >= 220000 && item.visible_area >= 55000);
  candidates.sort((a, b) => b.natural_area - a.natural_area);
  return {
    title: document.title || "",
    ready_state: document.readyState || "",
    has_body_text: bodyText.trim().length > 40,
    text: bodyText,
    large_image_ready: candidates.length > 0,
    large_image_url: candidates.length > 0 ? candidates[0].src : ""
  };
})())
"""


def _decode_screenshot_probe(payload) -> dict:  # noqa: ANN001
    if isinstance(payload, str) and payload:
        try:
            loaded = json.loads(payload)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _is_blocked_page_title(title: str) -> bool:
    text = str(title or "").strip().lower()
    if not text:
        return False
    blocked_terms = (
        "just a moment",
        "security verification",
        "checking your browser",
        "attention required",
        "access denied",
        "verify you are human",
        "cloudflare",
    )
    return any(term in text for term in blocked_terms)


def _screenshot_requires_large_image(url: str) -> bool:
    domain = _domain_no_www(urllib.parse.urlparse(url).netloc)
    return any(needle in domain for needle in ("superhivemarket.com", "blendermarket.com"))


def _looks_like_verification_text(text: str) -> bool:
    lowered = str(text or "").lower()
    if not lowered:
        return False
    terms = (
        "performing security verification",
        "security verification",
        "verify you are human",
        "checking your browser",
        "this page is displayed while the website verifies",
        "sorry, you have been blocked",
        "unable to access",
        "attention required",
        "正在进行安全验证",
        "正在验证",
    )
    return any(term in lowered for term in terms)


def _is_unusable_screenshot(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image = image.convert("RGB").resize((64, 64), Image.Resampling.BILINEAR)
            stat = ImageStat.Stat(image)
    except OSError:
        return True
    variance = sum(stat.var) / max(1, len(stat.var))
    return variance < 3


def _draw_generated_web_art(canvas: Image.Image, domain: str, platform: str, kind_label: str) -> None:
    draw = ImageDraw.Draw(canvas)
    base = _domain_color(domain)
    accent = ((base[0] + 92) % 180 + 40, (base[1] + 58) % 160 + 50, (base[2] + 124) % 150 + 60)
    deep = (max(18, base[0] - 28), max(22, base[1] - 28), max(28, base[2] - 28))
    draw.rectangle((0, 0, 900, 560), fill=base)
    draw.polygon([(560, 0), (900, 0), (900, 315), (650, 260)], fill=accent)
    draw.polygon([(0, 130), (320, 80), (900, 215), (900, 300), (0, 230)], fill=deep)
    for offset in range(-180, 900, 94):
        draw.line((offset, 560, offset + 310, 240), fill=(255, 255, 255), width=2)

    title = platform or domain or "Web Resource"
    title_font = _font(48, bold=True)
    label_font = _font(24, bold=True)
    small_font = _font(20)
    draw.text((42, 78), title[:34], fill=(255, 255, 255), font=title_font)
    if kind_label:
        draw.rounded_rectangle((42, 162, 42 + min(290, 34 + len(kind_label) * 24), 212), radius=12, fill=(255, 255, 255))
        draw.text((62, 174), kind_label[:12], fill=deep, font=label_font)
    if domain:
        draw.text((42, 238), _domain_no_www(domain), fill=(226, 236, 248), font=small_font)


def save_web_resource_bundle(card: dict, target_dir: Path) -> dict:
    if not is_web_card(card):
        return {"ok": False, "error": "这不是网页资源卡。"}
    url = str(card.get("source_url") or "").strip()
    if not url:
        return {"ok": False, "error": "网页资源缺少链接。"}
    title = str(card.get("display_name") or card.get("web_title") or card.get("name") or "Web Resource").strip()
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir = _unique_dir(target_dir / _safe_folder_name(title))
    bundle_dir.mkdir(parents=True, exist_ok=False)

    metadata = {
        "resource_kind": "web",
        "title": title,
        "url": url,
        "domain": card.get("web_domain") or "",
        "description": card.get("web_description") or "",
        "content_kind": card.get("web_content_kind") or "",
        "content_label": card.get("web_content_label") or "",
        "platform": card.get("web_platform") or "",
        "author": card.get("web_author") or "",
        "image_url": card.get("web_image_url") or "",
        "tags": card.get("content_tags") or [],
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (bundle_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (bundle_dir / "web-resource.url").write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")
    readme = "\n".join(
        [
            f"# {title}",
            "",
            f"- URL: {url}",
            f"- Domain: {metadata['domain']}",
            f"- Platform: {metadata['platform']}",
            f"- Type: {metadata['content_label'] or _content_kind_label(str(metadata['content_kind']))}",
            f"- Author: {metadata['author']}",
            "",
            str(metadata["description"] or "网页资源。"),
            "",
        ]
    )
    (bundle_dir / "README.md").write_text(readme, encoding="utf-8")
    preview = _preview_path_from_card(card)
    if preview and preview.exists():
        shutil.copy2(preview, bundle_dir / "preview.png")
    return {"ok": True, "folder_path": str(bundle_dir), "url_file": str(bundle_dir / "web-resource.url")}


def read_web_resource_card(path: Path) -> dict | None:
    path = Path(path)
    metadata_path = path / "metadata.json"
    url_path = path / "web-resource.url"
    if not metadata_path.exists() and not url_path.exists():
        return None
    data = {}
    if metadata_path.exists():
        try:
            loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    url = str(data.get("url") or _read_url_shortcut(url_path) or "").strip()
    if not url:
        return None
    title = str(data.get("title") or path.name)
    preview = path / "preview.png"
    content_kind = str(data.get("content_kind") or _infer_content_kind(title, str(data.get("description") or ""), url))
    content_label = str(data.get("content_label") or _content_kind_label(content_kind))
    platform = str(data.get("platform") or _platform_name(str(data.get("domain") or urllib.parse.urlparse(url).netloc)))
    return {
        "resource_kind": "web",
        "name": title,
        "display_name": title,
        "source_path": str(path),
        "source_url": url,
        "web_domain": data.get("domain") or urllib.parse.urlparse(url).netloc,
        "web_title": title,
        "web_description": data.get("description") or "",
        "web_content_kind": content_kind,
        "web_content_label": content_label,
        "web_platform": platform,
        "web_author": data.get("author") or "",
        "web_image_url": data.get("image_url") or "",
        "suggested_type": "tutorial" if _looks_like_learning_page(title, str(data.get("description") or ""), url) else "unknown",
        "confidence": "high",
        "content_tags": data.get("tags") or ["网页", content_label, platform],
        "target_suggestions": [],
        "target_path_hints": [str(path.parent)],
        "needs_human_review": False,
        "archive_count": 0,
        "source_archive_count": 0,
        "source_archives": [],
        "inspected_archives": 0,
        "virtual_archive_count": 0,
        "total_files": 1,
        "total_dirs": 0,
        "total_bytes": 0,
        "buckets": {"web": 1},
        "extension_counts": {},
        "archive_virtual_buckets": {},
        "archive_entry_samples": [],
        "preview_source": {"kind": "file", "path": str(preview)} if preview.exists() else None,
        "reasons": ["已入库的网页资源，打开按钮会直接打开原网页。"],
    }


def _download_image(url: str, base_path: Path) -> Path | None:
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    try:
        request = urllib.request.Request(url, headers=_browser_headers(url))
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("content-type", "")
            if "image" not in content_type.lower():
                return None
            data = response.read(MAX_IMAGE_BYTES + 1)
    except (urllib.error.URLError, OSError):
        return None
    if len(data) > MAX_IMAGE_BYTES:
        return None
    suffix = _image_suffix(url, content_type)
    path = base_path.with_suffix(suffix)
    path.write_bytes(data)
    return path


def _image_suffix(url: str, content_type: str) -> str:
    ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return ext
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    return ".jpg"


def _charset_from_content_type(content_type: str) -> str:
    match = re.search(r"charset=([^;\s]+)", content_type or "", re.IGNORECASE)
    return match.group(1).strip("\"'") if match else ""


def _decode_html(raw: bytes, charset: str) -> str:
    for encoding in (charset, "utf-8", "gb18030", "big5", "latin-1"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding, errors="replace")
        except LookupError:
            continue
    return raw.decode("utf-8", errors="replace")


def _first_text(*items: str | None) -> str:
    for item in items:
        text = " ".join(unescape(str(item or "")).split())
        if text:
            return text
    return ""


def _web_reasons(metadata: dict) -> list[str]:
    platform = metadata.get("platform") or metadata.get("domain") or "网页"
    kind = _content_kind_label(str(metadata.get("content_kind") or "webpage"))
    reasons = [f"网页资源：识别为 {platform} / {kind}，已尽量读取标题、描述和可用封面。"]
    if metadata.get("error"):
        reasons.append("网页内容读取失败，但链接本身仍可作为资源保存。")
    elif metadata.get("screenshot_preferred") or metadata.get("image_is_fallback"):
        reasons.append("网页没有提供可直接使用的封面图，软件会优先尝试生成网页截图；如果站点拦截截图，则生成网页信息封面。")
    elif metadata.get("image_url"):
        reasons.append("网页提供了封面图，已用于卡片预览。")
    elif not metadata.get("rich"):
        reasons.append("该页面没有提供足够的公开元信息，已使用平台和链接规则生成兜底卡片。")
    return reasons


def _looks_like_learning_page(title: str, description: str, url: str) -> bool:
    text = f"{title} {description} {url}".lower()
    terms = ("tutorial", "course", "lesson", "learn", "docs", "documentation", "guide", "教程", "课程", "文档")
    return any(term in text for term in terms)


def _safe_folder_name(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", text)
    text = " ".join(text.split()).strip(" .")
    return (text or "Web Resource")[:90]


def _unique_dir(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.name} ({index})")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法创建唯一网页资源目录：{path}")


def _preview_path_from_card(card: dict) -> Path | None:
    source = card.get("preview_source") or {}
    if isinstance(source, dict) and source.get("kind") == "file" and source.get("path"):
        return Path(str(source["path"]))
    return None


def _read_url_shortcut(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("url="):
                return line.split("=", 1)[1].strip()
    except OSError:
        return ""
    return ""


def _domain_color(domain: str) -> tuple[int, int, int]:
    digest = hashlib.sha1(domain.encode("utf-8", errors="ignore")).digest()
    return (48 + digest[0] % 80, 62 + digest[1] % 80, 76 + digest[2] % 80)


def _font(size: int, *, bold: bool = False):
    candidates = [
        Path(r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                pass
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int, max_lines: int) -> list[str]:  # noqa: ANN001
    text = " ".join(str(text or "").split())
    if not text:
        return []
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        width = draw.textbbox((0, 0), trial, font=font)[2]
        if width <= max_width or not current:
            current = trial
            continue
        lines.append(current)
        current = char
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len("".join(lines)) < len(text):
        lines[-1] = lines[-1].rstrip(". ") + "..."
    return lines
