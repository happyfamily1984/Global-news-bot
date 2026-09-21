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
        ],
    },
    {
        "code": "CN",
        "name_kr": "중국",
        "flag": "🇨🇳",
        "feeds": [
            "https://www.chinadaily.com.cn/rss/china_rss.xml",
            "http://www.xinhuanet.com/english/rss/chinarss.xml",
        ],
    },
    {
        "code": "GB",
        "name_kr": "영국",
        "flag": "🇬🇧",
        "feeds": [
            "http://feeds.bbci.co.uk/news/rss.xml",
            "https://www.theguardian.com/uk/rss",
        ],
    },
    {
        "code": "FR",
        "name_kr": "프랑스",
        "flag": "🇫🇷",
        "feeds": [
            "https://www.lemonde.fr/rss/une.xml",
            "https://www.france24.com/fr/rss",
        ],
    },
    {
        "code": "JP",
        "name_kr": "일본",
        "flag": "🇯🇵",
        "feeds": [
            "https://www3.nhk.or.jp/rss/news/cat0.xml",
            "https://www.japantimes.co.jp/feed/",
        ],
    },
    {
        "code": "IN",
        "name_kr": "인도",
        "flag": "🇮🇳",
        "feeds": [
            "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
            "https://www.thehindu.com/news/national/feeder/default.rss",
        ],
    },
    {
        "code": "BR",
        "name_kr": "브라질",
        "flag": "🇧🇷",
        "feeds": [
            "https://g1.globo.com/rss/g1/",
            "https://www.brasildefato.com.br/rss2.xml",
        ],
    },
    {
        "code": "SA",
        "name_kr": "사우디",
        "flag": "🇸🇦",
        "feeds": [
            "https://www.arabnews.com/rss.xml",
            "https://saudigazette.com.sa/rssFeed/1",
        ],
    },
]

# 국가당 Gemini에 넘길 헤드라인 후보 개수
CANDIDATES_PER_COUNTRY = 5

# Gemini 모델 (무료 티어에서 사용 가능한 모델, 환경변수로 override 가능)
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
