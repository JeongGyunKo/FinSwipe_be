"""
미국 주식 티커 → 회사명 매핑 (영문 + 한국어)
메모리 dict 조회 방식 — DB 추가 쿼리 없음
"""

TICKER_NAMES: dict[str, dict[str, str]] = {
    # 테크 대형주
    "AAPL":  {"corp": "Apple Inc.",               "ko": "애플"},
    "MSFT":  {"corp": "Microsoft Corp.",           "ko": "마이크로소프트"},
    "GOOGL": {"corp": "Alphabet Inc.",             "ko": "알파벳(구글)"},
    "GOOG":  {"corp": "Alphabet Inc.",             "ko": "알파벳(구글)"},
    "AMZN":  {"corp": "Amazon.com Inc.",           "ko": "아마존"},
    "META":  {"corp": "Meta Platforms Inc.",       "ko": "메타"},
    "TSLA":  {"corp": "Tesla Inc.",                "ko": "테슬라"},
    "NVDA":  {"corp": "NVIDIA Corp.",              "ko": "엔비디아"},
    "NFLX":  {"corp": "Netflix Inc.",              "ko": "넷플릭스"},
    "ORCL":  {"corp": "Oracle Corp.",              "ko": "오라클"},
    "CRM":   {"corp": "Salesforce Inc.",           "ko": "세일즈포스"},
    "NOW":   {"corp": "ServiceNow Inc.",           "ko": "서비스나우"},
    "SNOW":  {"corp": "Snowflake Inc.",            "ko": "스노우플레이크"},
    "ADBE":  {"corp": "Adobe Inc.",                "ko": "어도비"},
    "INTC":  {"corp": "Intel Corp.",               "ko": "인텔"},
    "AMD":   {"corp": "Advanced Micro Devices",    "ko": "AMD"},
    "QCOM":  {"corp": "Qualcomm Inc.",             "ko": "퀄컴"},
    "TSM":   {"corp": "Taiwan Semiconductor",      "ko": "TSMC"},
    "AVGO":  {"corp": "Broadcom Inc.",             "ko": "브로드컴"},
    "TXN":   {"corp": "Texas Instruments",         "ko": "텍사스 인스트루먼트"},
    "MU":    {"corp": "Micron Technology",         "ko": "마이크론"},
    "AMAT":  {"corp": "Applied Materials",         "ko": "어플라이드 머티리얼즈"},
    "LRCX":  {"corp": "Lam Research Corp.",        "ko": "램 리서치"},
    "KLAC":  {"corp": "KLA Corp.",                 "ko": "KLA"},
    "ASML":  {"corp": "ASML Holding",              "ko": "ASML"},
    # AI / 소프트웨어
    "PLTR":  {"corp": "Palantir Technologies",     "ko": "팔란티어"},
    "AI":    {"corp": "C3.ai Inc.",                "ko": "C3.ai"},
    "SOUN":  {"corp": "SoundHound AI",             "ko": "사운드하운드"},
    "BBAI":  {"corp": "BigBear.ai Holdings",       "ko": "빅베어 AI"},
    # 사이버보안
    "CRWD":  {"corp": "CrowdStrike Holdings",      "ko": "크라우드스트라이크"},
    "PANW":  {"corp": "Palo Alto Networks",        "ko": "팔로알토 네트웍스"},
    "FTNT":  {"corp": "Fortinet Inc.",             "ko": "포티넷"},
    "ZS":    {"corp": "Zscaler Inc.",              "ko": "즈스케일러"},
    "S":     {"corp": "SentinelOne Inc.",          "ko": "센티넬원"},
    "OKTA":  {"corp": "Okta Inc.",                 "ko": "옥타"},
    # 클라우드 / SaaS
    "DDOG":  {"corp": "Datadog Inc.",              "ko": "데이터도그"},
    "MDB":   {"corp": "MongoDB Inc.",              "ko": "몽고DB"},
    "NET":   {"corp": "Cloudflare Inc.",           "ko": "클라우드플레어"},
    "TWLO":  {"corp": "Twilio Inc.",               "ko": "트윌리오"},
    "ZM":    {"corp": "Zoom Video Communications", "ko": "줌"},
    "SHOP":  {"corp": "Shopify Inc.",              "ko": "쇼피파이"},
    "WDAY":  {"corp": "Workday Inc.",              "ko": "워크데이"},
    "HUBS":  {"corp": "HubSpot Inc.",              "ko": "허브스팟"},
    # 스트리밍 / 미디어
    "DIS":   {"corp": "The Walt Disney Co.",       "ko": "디즈니"},
    "CMCSA": {"corp": "Comcast Corp.",             "ko": "컴캐스트"},
    "WBD":   {"corp": "Warner Bros. Discovery",    "ko": "워너브라더스 디스커버리"},
    "PARA":  {"corp": "Paramount Global",          "ko": "파라마운트"},
    "SPOT":  {"corp": "Spotify Technology",        "ko": "스포티파이"},
    # 게임
    "ATVI":  {"corp": "Activision Blizzard",       "ko": "액티비전 블리자드"},
    "EA":    {"corp": "Electronic Arts",           "ko": "EA"},
    "TTWO":  {"corp": "Take-Two Interactive",      "ko": "테이크투 인터랙티브"},
    "RBLX":  {"corp": "Roblox Corp.",              "ko": "로블록스"},
    "U":     {"corp": "Unity Software",            "ko": "유니티"},
    # 금융
    "JPM":   {"corp": "JPMorgan Chase & Co.",      "ko": "JP모건"},
    "GS":    {"corp": "Goldman Sachs Group",       "ko": "골드만삭스"},
    "MS":    {"corp": "Morgan Stanley",            "ko": "모건스탠리"},
    "BAC":   {"corp": "Bank of America Corp.",     "ko": "뱅크오브아메리카"},
    "WFC":   {"corp": "Wells Fargo & Co.",         "ko": "웰스파고"},
    "C":     {"corp": "Citigroup Inc.",            "ko": "씨티그룹"},
    "BLK":   {"corp": "BlackRock Inc.",            "ko": "블랙록"},
    "AXP":   {"corp": "American Express Co.",      "ko": "아메리칸 익스프레스"},
    "COF":   {"corp": "Capital One Financial",     "ko": "캐피탈원"},
    "SCHW":  {"corp": "Charles Schwab Corp.",      "ko": "찰스슈왑"},
    # 핀테크 / 결제
    "V":     {"corp": "Visa Inc.",                 "ko": "비자"},
    "MA":    {"corp": "Mastercard Inc.",           "ko": "마스터카드"},
    "PYPL":  {"corp": "PayPal Holdings",           "ko": "페이팔"},
    "SQ":    {"corp": "Block Inc.",                "ko": "블록(스퀘어)"},
    "AFRM":  {"corp": "Affirm Holdings",           "ko": "어펌"},
    "COIN":  {"corp": "Coinbase Global",           "ko": "코인베이스"},
    # EV / 자동차
    "RIVN":  {"corp": "Rivian Automotive",         "ko": "리비안"},
    "LCID":  {"corp": "Lucid Group",               "ko": "루시드"},
    "F":     {"corp": "Ford Motor Co.",            "ko": "포드"},
    "GM":    {"corp": "General Motors Co.",        "ko": "GM"},
    # 헬스케어
    "JNJ":   {"corp": "Johnson & Johnson",         "ko": "존슨앤존슨"},
    "PFE":   {"corp": "Pfizer Inc.",               "ko": "화이자"},
    "MRNA":  {"corp": "Moderna Inc.",              "ko": "모더나"},
    "ABBV":  {"corp": "AbbVie Inc.",               "ko": "애브비"},
    "LLY":   {"corp": "Eli Lilly and Co.",         "ko": "일라이 릴리"},
    "BMY":   {"corp": "Bristol-Myers Squibb",      "ko": "브리스톨-마이어스 스퀴브"},
    "MRK":   {"corp": "Merck & Co.",               "ko": "머크"},
    "GILD":  {"corp": "Gilead Sciences",           "ko": "길리어드 사이언스"},
    "REGN":  {"corp": "Regeneron Pharmaceuticals", "ko": "리제네론"},
    "BIIB":  {"corp": "Biogen Inc.",               "ko": "바이오젠"},
    "ISRG":  {"corp": "Intuitive Surgical",        "ko": "인튜이티브 서지컬"},
    "UNH":   {"corp": "UnitedHealth Group",        "ko": "유나이티드헬스"},
    "HUM":   {"corp": "Humana Inc.",               "ko": "휴마나"},
    "CVS":   {"corp": "CVS Health Corp.",          "ko": "CVS 헬스"},
    # 에너지
    "XOM":   {"corp": "Exxon Mobil Corp.",         "ko": "엑슨모빌"},
    "CVX":   {"corp": "Chevron Corp.",             "ko": "셰브론"},
    "COP":   {"corp": "ConocoPhillips",            "ko": "코노코필립스"},
    "SLB":   {"corp": "SLB (Schlumberger)",        "ko": "슐럼버거"},
    "OXY":   {"corp": "Occidental Petroleum",      "ko": "옥시덴탈"},
    # 소재
    "FCX":   {"corp": "Freeport-McMoRan Inc.",     "ko": "프리포트-맥모란"},
    "NEM":   {"corp": "Newmont Corp.",             "ko": "뉴몬트"},
    "NUE":   {"corp": "Nucor Corp.",               "ko": "뉴코"},
    # 소비재 / 유통
    "WMT":   {"corp": "Walmart Inc.",              "ko": "월마트"},
    "TGT":   {"corp": "Target Corp.",              "ko": "타겟"},
    "COST":  {"corp": "Costco Wholesale",          "ko": "코스트코"},
    "NKE":   {"corp": "Nike Inc.",                 "ko": "나이키"},
    # 식음료
    "KO":    {"corp": "The Coca-Cola Co.",         "ko": "코카콜라"},
    "PEP":   {"corp": "PepsiCo Inc.",              "ko": "펩시코"},
    "MCD":   {"corp": "McDonald's Corp.",          "ko": "맥도날드"},
    "SBUX":  {"corp": "Starbucks Corp.",           "ko": "스타벅스"},
    # 여행 / 숙박
    "ABNB":  {"corp": "Airbnb Inc.",               "ko": "에어비앤비"},
    "MAR":   {"corp": "Marriott International",    "ko": "메리어트"},
    "HLT":   {"corp": "Hilton Worldwide",          "ko": "힐튼"},
    "BKNG":  {"corp": "Booking Holdings",         "ko": "부킹홀딩스"},
    "EXPE":  {"corp": "Expedia Group",             "ko": "익스피디아"},
    # 항공우주 / 방산
    "BA":    {"corp": "Boeing Co.",                "ko": "보잉"},
    "LMT":   {"corp": "Lockheed Martin Corp.",     "ko": "록히드마틴"},
    "RTX":   {"corp": "RTX Corp. (Raytheon)",      "ko": "레이시온"},
    "NOC":   {"corp": "Northrop Grumman",          "ko": "노스롭 그루만"},
    "GD":    {"corp": "General Dynamics",          "ko": "제너럴 다이내믹스"},
    # 산업재
    "CAT":   {"corp": "Caterpillar Inc.",          "ko": "캐터필러"},
    "DE":    {"corp": "Deere & Co.",               "ko": "디어(존 디어)"},
    "HON":   {"corp": "Honeywell International",   "ko": "하니웰"},
    "MMM":   {"corp": "3M Co.",                    "ko": "3M"},
    "GE":    {"corp": "GE Aerospace",              "ko": "GE 에어로스페이스"},
    # 통신
    "T":     {"corp": "AT&T Inc.",                 "ko": "AT&T"},
    "VZ":    {"corp": "Verizon Communications",    "ko": "버라이즌"},
    "TMUS":  {"corp": "T-Mobile US Inc.",          "ko": "T-모바일"},
    # 물류 / 운송
    "UPS":   {"corp": "United Parcel Service",     "ko": "UPS"},
    "FDX":   {"corp": "FedEx Corp.",               "ko": "페덱스"},
    "UNP":   {"corp": "Union Pacific Corp.",       "ko": "유니언 퍼시픽"},
    "CSX":   {"corp": "CSX Corp.",                 "ko": "CSX"},
    # REIT
    "PLD":   {"corp": "Prologis Inc.",             "ko": "프로로지스"},
    "SPG":   {"corp": "Simon Property Group",      "ko": "사이먼 프로퍼티"},
    "AVB":   {"corp": "AvalonBay Communities",     "ko": "아발론베이"},
    # 유틸리티
    "NEE":   {"corp": "NextEra Energy",            "ko": "넥스트에라 에너지"},
    "DUK":   {"corp": "Duke Energy Corp.",         "ko": "듀크 에너지"},
    "D":     {"corp": "Dominion Energy",           "ko": "도미니언 에너지"},
    "SO":    {"corp": "Southern Co.",              "ko": "서던 컴퍼니"},
    "EXC":   {"corp": "Exelon Corp.",              "ko": "엑셀론"},
    "ED":    {"corp": "Consolidated Edison",       "ko": "콘솔리데이티드 에디슨"},
}


def get_ticker_name(ticker: str) -> dict[str, str] | None:
    """티커 → {"corp": ..., "ko": ...} 반환. 없으면 None."""
    return TICKER_NAMES.get(ticker.upper())


def enrich_tickers(tickers: list[str]) -> list[dict[str, str]]:
    """
    티커 리스트 → ticker_names 리스트 반환.
    매핑 없는 티커는 corp/ko를 ticker 값으로 채워서 포함.
    """
    result = []
    for t in tickers:
        name = get_ticker_name(t)
        if name:
            result.append({"ticker": t, **name})
        else:
            result.append({"ticker": t, "corp": t, "ko": t})
    return result


def search_tickers(query: str) -> list[str]:
    """
    한국어/영문 회사명으로 티커 검색.
    query가 포함된 모든 티커 반환.
    예: "애플" → ["AAPL"], "apple" → ["AAPL"]
    """
    q = query.strip().lower()
    if not q:
        return []
    return [
        ticker
        for ticker, names in TICKER_NAMES.items()
        if q in names["ko"].lower() or q in names["corp"].lower() or q in ticker.lower()
    ]
