# Flairy v4 환경 변수 및 OAuth 리다이렉트 URI 가이드

소셜 로그인(구글·애플)과 인증 쿠키 설정을 위한 환경 변수 및 각 콘솔에서의 리다이렉트 URI 설정 방법을 정리합니다.

---

## 1. .env 예시

```env
# 데이터베이스
DATABASE_URL=postgresql://flairy_admin:flairy_secret@localhost:5432/flairy_v4

# JWT 및 쿠키
SECRET_KEY=your-secret-key-change-in-production
COOKIE_SECURE=false

# Google OAuth2
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback

# Apple Sign In
APPLE_CLIENT_ID=your-services-id
APPLE_TEAM_ID=your-team-id
APPLE_KEY_ID=your-key-id
APPLE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
APPLE_REDIRECT_URI=http://localhost:8000/api/auth/apple/callback
```

- **SECRET_KEY**: JWT 서명에 사용. 운영 환경에서는 반드시 강한 랜덤 값으로 설정.
- **COOKIE_SECURE**: `true`로 두면 쿠키가 HTTPS에서만 전송됨. 로컬 개발은 `false`, 운영은 `true` 권장.
- **APPLE_PRIVATE_KEY**: Apple에서 발급한 .p8 키 내용. 줄바꿈은 `\n`으로 넣거나 한 줄로 붙여 넣어도 됨.

---

## 2. 구글 OAuth 설정

1. [Google Cloud Console](https://console.cloud.google.com/) → **API 및 서비스** → **사용자 인증 정보**
2. **사용자 인증 정보 만들기** → **OAuth 클라이언트 ID**
3. 애플리케이션 유형: **웹 애플리케이션**
4. **승인된 리다이렉트 URI**에 아래를 추가:
   - 로컬: `http://localhost:8000/api/auth/google/callback`
   - 운영: `https://your-domain.com/api/auth/google/callback`
5. 생성된 **클라이언트 ID**와 **클라이언트 보안 비밀**을 `.env`의 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`에 넣기
6. `GOOGLE_REDIRECT_URI`는 위에서 등록한 URI와 **완전히 동일**해야 함 (트레일링 슬래시 등 주의)

---

## 3. 애플 Sign In 설정

1. [Apple Developer](https://developer.apple.com/) → **Certificates, Identifiers & Profiles** → **Identifiers**
2. **Services ID** 생성(또는 기존 App ID에 Sign In with Apple 활성화 후 Services ID 사용)
3. 해당 Services ID에서 **Sign In with Apple** 설정:
   - **Return URLs**에 추가:
     - 로컬: `http://localhost:8000/api/auth/apple/callback`
     - 운영: `https://your-domain.com/api/auth/apple/callback`
4. **Keys**에서 **Sign In with Apple**용 키 생성 → .p8 파일 다운로드. **Key ID**와 **Team ID**, **Client ID(Services ID)**를 .env에 넣기
5. **APPLE_PRIVATE_KEY**에는 .p8 파일 내용 전체를 문자열로 넣기 (줄바꿈은 `\n` 또는 실제 줄바꿈)

리다이렉트 URI가 콘솔에 등록된 값과 앱의 `APPLE_REDIRECT_URI`가 정확히 일치해야 콜백이 동작합니다.

---

## 4. 쿠키 보안 (v4 인증)

- **HttpOnly**: 스크립트에서 접근 불가, XSS로 토큰 탈취 완화.
- **SameSite**: `Lax` 또는 `Strict`. CSRF·외부 사이트 요청 시 쿠키 전송 제어.
- **Secure**: 운영(HTTPS)에서는 반드시 `true`. 로컬 HTTP에서는 `false`.

앱에서는 이미 `set_cookie(..., httponly=True, samesite="lax", secure=os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1"))` 로 설정하고 있으므로, 운영 배포 시 `.env`에 `COOKIE_SECURE=true`만 설정하면 됩니다.
