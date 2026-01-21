# Frontend (Next.js 14)

특허 AI 검색 시스템 프론트엔드

## 실행

```bash
npm install
npm run dev      # 개발 서버 (포트 3002)
npm run build    # 프로덕션 빌드
```

## 디렉토리 구조

```
frontend/
├── app/                      # Next.js App Router
│   ├── layout.tsx           # 공통 레이아웃
│   ├── page.tsx             # 메인 페이지
│   ├── easy/                # Easy 모드 (초등학생용)
│   ├── visualization/       # 시각화 페이지
│   └── api/                 # API Routes (SSE 프록시)
├── components/
│   ├── easy/                # Easy 모드 컴포넌트
│   │   └── EasyChat.tsx     # 채팅 인터페이스
│   └── patent/              # 특허 관련 컴포넌트
│       └── PerspectiveTable.tsx  # 관점별 요약 표
└── .env.local               # 환경 변수
```

## 환경 변수

```bash
# .env.local
NEXT_PUBLIC_API_URL=/api     # API 프록시 경로
BACKEND_URL=http://localhost:8000  # 백엔드 URL (서버사이드)
```

## 주요 컴포넌트

### PerspectiveTable
특허의 4가지 관점(목적/소재/공법/효과)을 표 형식으로 표시

### EasyChat
L1 레벨(초등학생) 대상 채팅 인터페이스, SSE 스트리밍 지원
