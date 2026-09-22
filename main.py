"""글로벌 뉴스 텔레그램 알림봇.

동작 순서:
1. 국가별 메인 언론사 RSS에서 헤드라인 후보를 수집한다 (실패 시 예비 피드로 재시도).
2. 수집된 헤드라인을 Gemini API에 보내 국가별 가장 중요한 뉴스 1건을 한국어로 요약받는다.
3. Gemini 호출이 실패해도 원문 헤드라인으로 대체하여 항상 메시지를 전송한다.
4. 완성된 메시지를 텔레그램으로 전송한다.
"""

import calendar
import html
import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import feedparser
import requests

from config import (
    CANDIDATES_PER_COUNTRY,
    COUNTRIES,
    FRESHNESS_WINDOW_HOURS,
    GEMINI_MODEL_CANDIDATES,
    RESULTS_PER_COUNTRY,
)

TELEGRAM_MAX_CHARS = 3500

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 10
MAX_RETRIES = 2
# 재시도해봐야 결과가 바뀌지 않는 HTTP 상태코드 (차단/삭제된 리소스)
PERMANENT_FAILURE_STATUS = {401, 403, 404, 410}


def fetch_url(url: str):
    """requests로 피드를 받아온다. 실패 시 None을 반환한다 (예외를 던지지 않음)."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            return resp.content
        except requests.exceptions.HTTPError as exc:
            print(f"[warn] fetch failed ({url}): {exc}", file=sys.stderr)
            status = exc.response.status_code if exc.response is not None else None
            if status in PERMANENT_FAILURE_STATUS:
                return None  # 재시도해도 소용없음
        except Exception as exc:  # noqa: BLE001 - 어떤 실패든 조용히 재시도/포기
            print(f"[warn] fetch failed ({url}): {exc}", file=sys.stderr)
        if attempt < MAX_RETRIES:
            time.sleep(1.5 * (attempt + 1))
    return None


def _entry_age_hours(entry) -> float | None:
    """항목의 발행/수정 시각 기준 경과 시간(시간 단위). 알 수 없으면 None."""
    for field in ("published_parsed", "updated_parsed"):
        struct = getattr(entry, field, None)
        if struct:
            try:
                published_epoch = calendar.timegm(struct)
                return max(0.0, (time.time() - published_epoch) / 3600)
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def _entries_to_headlines(entries) -> list[dict]:
    headlines = []
    for entry in entries[:CANDIDATES_PER_COUNTRY]:
        title = getattr(entry, "title", "").strip()
        if not title:
            continue
        summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
        link = getattr(entry, "link", "")
        headlines.append({"title": title, "summary": summary[:300], "link": link})
    return headlines


def fetch_country_headlines(country: dict) -> list[dict]:
    """국가의 feeds를 순서대로 시도해 헤드라인 후보 목록을 반환한다.

    각 피드에서 최근(FRESHNESS_WINDOW_HOURS 이내) 항목을 우선 채택하고,
    끝까지 최근 항목이 없으면 가장 먼저 성공한 피드의 결과를 그대로 사용한다.
    """
    stale_fallback = None

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

        recent_entries = [
            e
            for e in entries
            if (age := _entry_age_hours(e)) is None or age <= FRESHNESS_WINDOW_HOURS
        ]
        headlines = _entries_to_headlines(recent_entries or entries)
        if not headlines:
            continue

        if recent_entries:
            return headlines
        if stale_fallback is None:
            print(f"[warn] no recent entries in {feed_url}, trying next feed", file=sys.stderr)
            stale_fallback = headlines

    if stale_fallback:
        print(f"[warn] using stale headlines for {country['code']} (no fresh feed found)", file=sys.stderr)
        return stale_fallback

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
        f"각 국가마다 가장 중요하고 의미 있는 뉴스를 최대 {RESULTS_PER_COUNTRY}건 선택하세요.",
        "후보가 그보다 적으면 있는 만큼만 선택하세요.",
        "",
        "선택 기준(중요):",
        "- 그 국가의 국내 뉴스뿐 아니라, 그 국가가 관련되거나 영향을 받는 국제 뉴스도 좋습니다.",
        "- 다만 그 국가와 사실상 관련이 없는, 다른 나라만의 이야기를 단순히 전재한 기사"
        "(예: 프랑스 언론사 기사지만 내용은 프랑스와 무관한 순수 미국 국내 정치)는 우선순위를 낮추세요.",
        "- 같은 국가 안에서는 서로 다른 주제/사건을 다루도록 다양성을 주세요(같은 사건의 후속 기사 반복 금지).",
        "",
        "선택한 각 뉴스는 한국어로 제목(한 줄, 20자 내외)과 2문장 이내 요약을 작성하세요.",
        "후보가 없는 국가는 결과에서 제외하세요.",
        "",
        "마지막으로, 위에서 선택한 뉴스 전체를 종합해서 현재 국제정세를 분석하는 글을 작성하세요.",
        "개별 뉴스 요약이 아니라, 국가들을 넘나드는 공통된 흐름/긴장/기회 요인을 짚어주세요",
        "(예: 특정 국가 간 외교 이슈가 여러 국가에 걸쳐 동시에 보도되는 경우, 경제/안보 트렌드 등).",
        "한국어로 4~6문장 분량으로 작성하세요.",
        "",
        "반드시 아래 JSON 객체 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요:",
        '{"items": [{"country_code": "US", "title_kr": "...", "summary_kr": "...", "link": "..."}, ...], '
        '"analysis": "..."}',
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


# 재시도해도 소용없고, 다른 모델을 시도해도 결과가 같을 상태코드 (API 키/권한 문제)
ACCOUNT_LEVEL_FAILURE_STATUS = {401, 403}
# 429(rate limit)/5xx(과부하) 재시도 간 대기 시간(초). Retry-After 헤더가 있으면 그쪽을 우선한다.
GEMINI_RETRY_DELAYS = [3, 8, 20]


def discover_gemini_models(api_key: str) -> list[str]:
    """이 API 키로 실제 generateContent를 지원하는 모델 이름 목록을 조회한다.

    모델 이름을 하드코딩해서 추측하는 대신, 계정/API 버전에 따라 달라질 수 있는
    실제 사용 가능한 모델을 API에 직접 물어본다. 실패하면 빈 리스트를 반환한다.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] gemini model discovery failed: {exc}", file=sys.stderr)
        return []

    names = []
    for m in data.get("models", []):
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        name = m.get("name", "")
        short = name.split("/", 1)[1] if "/" in name else name
        if short:
            names.append(short)

    # flash 계열을 우선 시도 (무료 티어 쿼터에 더 적합)
    names.sort(key=lambda n: (0 if "flash" in n else 1, n))
    print(f"[info] gemini models available for this key: {names}")
    return names


def _call_gemini_model(model: str, api_key: str, prompt: str) -> tuple[dict | None, bool]:
    """(결과 {"items": [...], "analysis": "..."}, 다른_모델로_넘어갈지) 튜플을 반환한다."""
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

    for attempt in range(len(GEMINI_RETRY_DELAYS) + 1):
        retry_after = None
        try:
            resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
                return parsed, False
            print(f"[warn] gemini({model}) response is not the expected object shape", file=sys.stderr)
            return None, True  # 응답 형식 문제 -> 혹시 다른 모델은 다를 수 있으니 시도
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            print(f"[warn] gemini({model}) call failed (attempt {attempt}): {exc}", file=sys.stderr)
            if status in ACCOUNT_LEVEL_FAILURE_STATUS:
                return None, False  # 키/권한 문제는 모델을 바꿔도 동일하게 실패함
            if status == 404:
                return None, True  # 이 모델이 없음 -> 다음 모델 후보로 즉시 넘어감
            if exc.response is not None:
                retry_after = exc.response.headers.get("Retry-After")
            # 429(rate limit), 5xx(서버 과부하/장애) 등은 아래에서 재시도 후 다음 모델로 넘어감
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] gemini({model}) call failed (attempt {attempt}): {exc}", file=sys.stderr)

        if attempt < len(GEMINI_RETRY_DELAYS):
            wait = GEMINI_RETRY_DELAYS[attempt]
            if retry_after:
                try:
                    wait = min(float(retry_after), 30)
                except ValueError:
                    pass
            time.sleep(wait)

    return None, True  # 이 모델에서 재시도를 다 썼으니 다음 모델 후보로 넘어감


def call_gemini(prompt: str) -> dict | None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[warn] GEMINI_API_KEY not set, skipping AI 분석", file=sys.stderr)
        return None

    env_model = os.environ.get("GEMINI_MODEL")
    discovered = discover_gemini_models(api_key)
    candidates = ([env_model] if env_model else []) + discovered + GEMINI_MODEL_CANDIDATES
    # 중복 제거(순서 유지)
    candidates = list(dict.fromkeys(c for c in candidates if c))

    for model in candidates:
        result, try_next = _call_gemini_model(model, api_key, prompt)
        if result is not None:
            print(f"[info] gemini model used: {model}")
            return result
        if not try_next:
            break  # 모델은 찾았지만 다른 이유로 실패 -> 더 시도해봐야 소용없음

    return None


def fallback_results(all_headlines: dict) -> list[dict]:
    """Gemini 호출 실패 시 국가별 상위 헤드라인을 원문 그대로 사용."""
    results = []
    for country in COUNTRIES:
        candidates = all_headlines.get(country["code"], [])
        for top in candidates[:RESULTS_PER_COUNTRY]:
            results.append(
                {
                    "country_code": country["code"],
                    "title_kr": top["title"],
                    "summary_kr": "(AI 요약 실패로 원문 제목만 표시됩니다.)",
                    "link": top["link"],
                }
            )
    return results


def build_country_sections(results: list[dict]) -> list[str]:
    """국가별로 결과를 묶어 '국기 이름\n1. ...\n2. ...' 형태의 섹션 문자열 목록을 만든다."""
    flag_by_code = {c["code"]: c["flag"] for c in COUNTRIES}
    name_by_code = {c["code"]: c["name_kr"] for c in COUNTRIES}

    by_code: dict[str, list[dict]] = {}
    for item in results:
        by_code.setdefault(item.get("country_code", ""), []).append(item)

    sections = []
    for country in COUNTRIES:
        items = by_code.get(country["code"])
        if not items:
            continue
        flag = flag_by_code[country["code"]]
        name = name_by_code[country["code"]]
        lines = [f"{flag} <b>{html.escape(name)}</b>"]
        for i, item in enumerate(items, 1):
            title = html.escape(item.get("title_kr", "").strip())
            summary = html.escape(item.get("summary_kr", "").strip())
            link = item.get("link", "").strip()
            lines.append(f"{i}. {title}")
            if summary:
                lines.append(f"   {summary}")
            if link:
                lines.append(f'   <a href="{html.escape(link, quote=True)}">링크</a>')
        sections.append("\n".join(lines))

    return sections


def build_telegram_messages(
    results: list[dict], analysis: str | None, slot_label: str, now_kst: datetime
) -> list[str]:
    """텔레그램 글자수 제한을 넘지 않도록 결과를 여러 메시지로 나눈다."""
    header = f"🌍 글로벌 뉴스 브리핑 ({now_kst.strftime('%Y-%m-%d')} {slot_label})"
    sections = build_country_sections(results)

    if not sections:
        return [header + "\n\n오늘은 수집된 헤드라인이 없습니다."]

    analysis = (analysis or "").strip()
    if analysis:
        sections = sections + [f"🧭 <b>종합 국제정세 분석</b>\n{html.escape(analysis)}"]

    groups: list[list[str]] = []
    current: list[str] = []
    current_len = len(header)
    for sec in sections:
        add_len = len(sec) + 2
        if current and current_len + add_len > TELEGRAM_MAX_CHARS:
            groups.append(current)
            current = []
            current_len = len(header)
        current.append(sec)
        current_len += add_len
    if current:
        groups.append(current)

    total = len(groups)
    messages = []
    for i, group in enumerate(groups, 1):
        page_header = header if total == 1 else f"{header} ({i}/{total})"
        messages.append(page_header + "\n\n" + "\n\n".join(group))
    return messages


def send_telegram_message(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 필요합니다.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
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

    gemini_output = None
    if collected > 0:
        prompt = build_gemini_prompt(all_headlines)
        gemini_output = call_gemini(prompt)

    if gemini_output:
        results = gemini_output.get("items", [])
        analysis = gemini_output.get("analysis", "")
    else:
        print("[info] using fallback (raw headlines) results")
        results = fallback_results(all_headlines)
        analysis = None  # AI 분석 실패 시 종합 분석은 생략

    messages = build_telegram_messages(results, analysis, slot_label_for(now_kst), now_kst)
    for i, message in enumerate(messages, 1):
        print(f"[info] sending telegram message {i}/{len(messages)}:\n" + message)
        send_telegram_message(message)
    print("[info] done")


if __name__ == "__main__":
    main()
