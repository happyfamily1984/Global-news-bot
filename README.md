# Global News Bot

미국·중국·영국·프랑스·일본·인도·브라질·사우디 8개국 메인 언론사 헤드라인을
Gemini API로 분석/요약해서 하루 3번(오전 9시·오후 1시·저녁 9시, KST) 텔레그램으로
보내주는 알림봇입니다.

## 동작 방식

1. `config.py`에 등록된 국가별 RSS 피드에서 최신 헤드라인 후보를 가져옵니다.
   (기본 피드가 실패하면 예비 피드로 자동 전환)
2. 수집된 후보를 Gemini API에 보내 국가별로 가장 중요한 뉴스 1건을 한국어 제목 +
   2문장 요약으로 정리합니다.
3. Gemini 호출이 실패해도 원문 헤드라인으로 대체해 메시지를 반드시 전송합니다.
4. 텔레그램 봇으로 최종 메시지를 전송합니다.

GitHub Actions가 매일 KST 09:00 / 13:00 / 21:00에 자동으로 실행합니다
(`.github/workflows/news-bot.yml`).

## 준비물

1. **텔레그램 봇 토큰**
   - 텔레그램에서 [@BotFather](https://t.me/BotFather)에게 `/newbot`으로 봇 생성 → 토큰 발급
2. **텔레그램 채팅 ID**
   - 만든 봇과 대화를 한 번 시작한 뒤, 브라우저에서
     `https://api.telegram.org/bot<TOKEN>/getUpdates` 접속 → `chat.id` 확인
   - 또는 [@userinfobot](https://t.me/userinfobot)으로 본인 ID 확인
3. **Gemini API 키**
   - [Google AI Studio](https://aistudio.google.com/apikey)에서 무료로 발급

## GitHub 저장소 설정

Repository → Settings → Secrets and variables → Actions 에 아래 3개를 등록하세요.

| Secret 이름 | 설명 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather에서 받은 토큰 |
| `TELEGRAM_CHAT_ID` | 메시지를 받을 채팅 ID |
| `GEMINI_API_KEY` | Google AI Studio에서 받은 키 |

등록 후 Actions 탭 → "Global News Bot" → "Run workflow"로 즉시 테스트할 수 있습니다.

## 로컬 실행

```bash
pip install -r requirements.txt
cp .env.example .env  # 값 채우기
export $(cat .env | xargs)  # 또는 direnv/dotenv 사용
python main.py
```

## 국가/언론사 변경

`config.py`의 `COUNTRIES` 리스트에서 국가별 RSS 피드 URL을 수정하거나 추가할 수 있습니다.
피드가 죽으면 자동으로 다음 피드(fallback)를 시도합니다.
