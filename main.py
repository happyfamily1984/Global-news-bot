"""글로벌 뉴스 텔레그램 알림봇.

동작 순서:
1. 국가별 메인 언론사 RSS에서 헤드라인 후보를 수집한다 (실패 시 예비 피드로 재시도).
2. 수집된 헤드라인을 Gemini API에 보내 국가별 가장 중요한 뉴스 1건을 한국어로 요약받는다.
3. Gemini 호출이 실패해도 원문 헤드라인으로 대체하여 항상 메시지를 전송한다.
4. 완성된 메시지를 텔레그램으로 전송한다.
"""

import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import feedparser
import requests

from config import CANDIDATES_PER_COUNTRY, COUNTRIES, DEFAULT_GEMINI_MODEL

USER_AGENT = (
    "Mozilla/5.0 (compatible; GlobalNewsBot/1.0; "
    "+https://github.com/happyfamily1984/global-news-bot)"
)
REQUEST_TIMEOUT = 10
MAX_RETRIES = 2


def fetch_url(url: str):
    """requests로 피드를 받아온다. 실패 시 None을 반환한다 (예외를 던지지 않음)."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            return resp.content
        except Exception as exc:  # noqa: BLE001 - 어떤 실패든 조용히 재시도/포기
            print(f"[warn] fetch failed ({url}): {exc}", file=sys.stderr)
            if attempt < MAX_RETRIES:
                time.sleep(1.5 * (attempt + 1))
    return None


def fetch_country_headlines(country: dict) -> list[dict]:
    """국가의 feeds를 순서대로 시도해 헤드라인 후보 목록을 반환한다."""
    for feed_url in country["feeds"]:
        content = fetch_url(feed_url)
        if not content:
            continue
        try:
            parsed = feedparser.parse(content)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] parse failed ({feed_url}): {exc}", file=sys.stderr)
            continue

        entries = getattr(parsed, "entries", [])
        if not entries:
            continue

        headlines = []
        for entry in entries[:CANDIDATES_PER_COUNTRY]:
            title = getattr(entry, "title", "").strip()
            if not title:
                continue
            summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
            link = getattr(entry, "link", "")
            headlines.append({"title": title, "summary": summary[:300], "link": link})

        if headlines:
            return headlines

    print(f"[warn] all feeds failed for {country['code']}", file=sys.stderr)
    return []


def collect_all_headlines() -> dict:
    """국가 코드 -> 헤드라인 후보 리스트."""
    result = {}
    for country in COUNTRIES:
        result[country["code"]] = fetch_country_headlines(country)
    return result


def build_gemini_prompt(all_headlines: dict) -> str:
    lines = [
        "당신은 글로벌 뉴스 에디터입니다.",
        "아래는 국가별 주요 언론사에서 수집한 오늘의 헤드라인 후보 목록입니다.",
        "각 국가마다 전 세계적으로 가장 중요하고 의미 있는 뉴스를 1건씩만 선택하세요.",
        "선택한 뉴스는 한국어로 제목(한 줄, 15자 내외)과 2문장 이내 요약을 작성하세요.",
        "후보가 없는 국가는 결과에서 제외하세요.",
        "",
        "반드시 아래 JSON 배열 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요:",
        '[{"country_code": "US", "title_kr": "...", "summary_kr": "...", "link": "..."}, ...]',
        "",
        "### 헤드라인 후보",
    ]

    for country in COUNTRIES:
        code = country["code"]
        candidates = all_headlines.get(code, [])
        if not candidates:
            continue
        lines.append(f"\n[{code} / {country['name_kr']}]")
        for i, item in enumerate(candidates, 1):
            lines.append(f"{i}. {item['title']} - {item['summary']} ({item['link']})")

    return "\n".join(lines)


def call_gemini(prompt: str) -> list[dict] | None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[warn] GEMINI_API_KEY not set, skipping AI 분석", file=sys.stderr)
        return None

    model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.3,
        },
    }

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            print("[warn] gemini response is not a list", file=sys.stderr)
            return None
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] gemini call failed (attempt {attempt}): {exc}", file=sys.stderr)
            if attempt < MAX_RETRIES:
                time.sleep(2 * (attempt + 1))

    return None


def fallback_results(all_headlines: dict) -> list[dict]:
    """Gemini 호출 실패 시 국가별 첫 번째 헤드라인을 원문 그대로 사용."""
    results = []
    for country in COUNTRIES:
        candidates = all_headlines.get(country["code"], [])
        if not candidates:
            continue
        top = candidates[0]
        results.append(
            {
                "country_code": country["code"],
                "title_kr": top["title"],
                "summary_kr": "(AI 요약 실패로 원문 제목만 표시됩니다.)",
                "link": top["link"],
            }
        )
    return results


def format_telegram_message(results: list[dict], slot_label: str, now_kst: datetime) -> str:
    flag_by_code = {c["code"]: c["flag"] for c in COUNTRIES}
    name_by_code = {c["code"]: c["name_kr"] for c in COUNTRIES}

    header = f"🌍 글로벌 뉴스 브리핑 ({now_kst.strftime('%Y-%m-%d')} {slot_label})"
    lines = [header, ""]

    if not results:
        lines.append("오늘은 수집된 헤드라인이 없습니다.")
    else:
        for item in results:
            code = item.get("country_code", "")
            flag = flag_by_code.get(code, "🏳️")
            name = name_by_code.get(code, code)
            title = item.get("title_kr", "").strip()
            summary = item.get("summary_kr", "").strip()
            link = item.get("link", "")

            lines.append(f"{flag} {name}: {title}")
            if summary:
                lines.append(summary)
            if link:
                lines.append(link)
            lines.append("")

    message = "\n".join(lines).strip()
    if len(message) > 4000:
        message = message[:3990] + "\n...(생략)"
    return message


def send_telegram_message(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 필요합니다.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] telegram send failed (attempt {attempt}): {exc}", file=sys.stderr)
            if attempt < MAX_RETRIES:
                time.sleep(2 * (attempt + 1))

    raise RuntimeError("텔레그램 메시지 전송에 반복적으로 실패했습니다.")


def slot_label_for(now_kst: datetime) -> str:
    hour = now_kst.hour
    if hour < 12:
        return "오전 브리핑"
    if hour < 18:
        return "오후 브리핑"
    return "저녁 브리핑"


def main() -> None:
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    print(f"[info] run started at {now_kst.isoformat()}")

    all_headlines = collect_all_headlines()
    collected = sum(1 for v in all_headlines.values() if v)
    print(f"[info] collected headlines for {collected}/{len(COUNTRIES)} countries")

    results = None
    if collected > 0:
        prompt = build_gemini_prompt(all_headlines)
        results = call_gemini(prompt)

    if not results:
        print("[info] using fallback (raw headlines) results")
        results = fallback_results(all_headlines)

    message = format_telegram_message(results, slot_label_for(now_kst), now_kst)
    print("[info] sending telegram message:\n" + message)

    send_telegram_message(message)
    print("[info] done")


if __name__ == "__main__":
    main()
