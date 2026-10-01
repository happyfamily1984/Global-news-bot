"""국가별 메인 언론사 RSS 설정.

각 국가는 기본(primary) 피드와 예비(fallback) 피드를 가진다.
기본 피드 수집이 실패하면 예비 피드로 자동 전환하여 오류 없이 동작하도록 한다.
"""

COUNTRIES = [
    {
        "code": "US",
        "name_kr": "미국",
        "flag": "🇺🇸",
        "feeds": [
            "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
            "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
            "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        ],
    },
    {
        "code": "CN",
        "name_kr": "중국",
        "flag": "🇨🇳",
        "feeds": [
            "https://www.globaltimes.cn/rss/china.xml",
            "http://www.xinhuanet.com/english/rss/chinarss.xml",
            "https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        ],
    },
    {
        "code": "GB",
        "name_kr": "영국",
        "flag": "🇬🇧",
        "feeds": [
            "http://feeds.bbci.co.uk/news/rss.xml",
            "https://www.theguardian.com/uk/rss",
            "https://news.google.com/rss?hl=en-GB&gl=GB&ceid=GB:en",
        ],
    },
    {
        "code": "FR",
        "name_kr": "프랑스",
        "flag": "🇫🇷",
        "feeds": [
            "https://www.lemonde.fr/rss/une.xml",
            "https://www.france24.com/fr/rss",
            "https://news.google.com/rss?hl=fr&gl=FR&ceid=FR:fr",
        ],
    },
    {
        "code": "JP",
        "name_kr": "일본",
        "flag": "🇯🇵",
        "feeds": [
            "https://www3.nhk.or.jp/rss/news/cat0.xml",
            "https://www.japantimes.co.jp/feed/",
            "https://news.google.com/rss?hl=ja&gl=JP&ceid=JP:ja",
        ],
    },
]

# 국가당 Gemini에 넘길 헤드라인 후보 개수
CANDIDATES_PER_COUNTRY = 8

# 국가당 최종적으로 선택/전송할 뉴스 건수
RESULTS_PER_COUNTRY = 3

# 이 시간(시간) 이내에 게시된 항목만 "최신"으로 취급한다. 발행일이 없는 항목은 판단 불가로 보고 포함한다.
FRESHNESS_WINDOW_HOURS = 72

# Gemini 모델 후보 (앞에서부터 순서대로 시도, 존재하지 않는 모델은 자동으로 건너뜀).
# GEMINI_MODEL 환경변수를 지정하면 그 모델을 가장 먼저 시도한다.
GEMINI_MODEL_CANDIDATES = [
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]
