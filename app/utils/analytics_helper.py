from __future__ import annotations

from urllib.parse import urlparse


def parse_device_type(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "ipad" in ua or "tablet" in ua:
        return "Tablet"
    if any(k in ua for k in ["iphone", "android", "mobile", "kakaotalk", "instagram"]):
        return "Mobile"
    return "PC"


def parse_os_name(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if any(k in ua for k in ["iphone", "ipad", "ios"]):
        return "iOS"
    if "android" in ua:
        return "Android"
    if "windows" in ua:
        return "Windows"
    if any(k in ua for k in ["mac os", "macintosh"]):
        return "macOS"
    if "linux" in ua:
        return "Linux"
    return "Unknown"


def parse_browser_name(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "kakaotalk" in ua:
        return "KakaoTalk"
    if "instagram" in ua:
        return "Instagram"
    if "whale" in ua:
        return "Whale"
    if "edg/" in ua or "edge/" in ua:
        return "Edge"
    if "samsungbrowser" in ua:
        return "Samsung Internet"
    if "chrome" in ua and "safari" in ua and "whale" not in ua:
        return "Chrome"
    if "safari" in ua and "chrome" not in ua:
        return "Safari"
    if "firefox" in ua:
        return "Firefox"
    return "Unknown"


def parse_inflow_channel(referrer: str | None, utm_source: str | None) -> str:
    src = (utm_source or "").strip().lower()
    if src:
        if "insta" in src:
            return "instagram"
        if "kakao" in src:
            return "kakaotalk"
        if "naver" in src:
            return "naver"
        if "google" in src:
            return "google"
        if "meta" in src or "facebook" in src:
            return "facebook"
        if "youtube" in src:
            return "youtube"
        return src[:50]

    ref = (referrer or "").strip().lower()
    if not ref:
        return "direct"
    try:
        host = (urlparse(ref).hostname or "").lower()
    except Exception:
        host = ref
    if "instagram.com" in host:
        return "instagram"
    if "kakao.com" in host:
        return "kakaotalk"
    if "naver.com" in host:
        return "naver"
    if "google." in host:
        return "google"
    if "facebook.com" in host or "m.facebook.com" in host:
        return "facebook"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "flairy.kr" in host:
        return "internal"
    return "referral"
