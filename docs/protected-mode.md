# 선택형 보호 모드

기본 `HARBINGER_PROTECTED_MODE=false`는 기존 합성 공개 데모다. 실제 자료는 보호 모드와 HTTPS 뒤에서만 사용한다. 보호 모드에서 계정 파일 또는 origin이 없거나 잘못되면 서비스 시작이 실패한다. 공개 기본 계정은 없다.

## 계정 설정

```sh
python -m harbinger.auth_users /run/secrets/harbinger-users.json alice --role operator --site S01
```

암호는 터미널 `getpass`로 두 번 입력한다. 명령행·환경변수로 암호를 받지 않는다. 12–256자 암호를 매번 다른 128비트 salt와 고정 scrypt(N=16384,r=8,p=1)로 해시한다. JSON에는 사용자 이름, 역할, 허용 사이트, 해시만 저장한다. 도구는 임시 파일을 검사한 뒤 원자적으로 0600 파일로 교체한다. 계정 변경·암호 재설정·삭제 후 재시작하면 모든 로그인과 업로드 세션이 취소된다. 계정 파일은 저장소에 커밋하지 않는다.

```sh
export HARBINGER_PROTECTED_MODE=1
export HARBINGER_AUTH_USERS_FILE=/run/secrets/harbinger-users.json
export HARBINGER_AUTH_ORIGIN=https://harbinger.example.com
uvicorn harbinger.api.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log
```

Origin은 경로·후행 슬래시 없이 브라우저에서 사용하는 정확한 origin이다. HTTPS reverse proxy가 이 주소를 서비스해야 한다. API 호출도 변경 요청에는 `Origin`과 로그인 또는 `/auth/me`의 `csrf_token`을 `X-CSRF-Token` 헤더로 보낸다. 로그인 자체는 Origin 검사를 받는다. 브라우저 쿠키는 HttpOnly, SameSite=Strict, Secure가 기본이며 JS는 CSRF 토큰만 메모리에 둔다. 로그인 토큰을 localStorage에 저장하지 않는다. 세션 ID가 URL 경로에 포함될 수 있으므로 서비스와 프록시의 access log는 비활성화하거나 해당 경로를 가린다. API 메트릭은 경로 템플릿을 사용한다.

| 역할 | 권한 |
|---|---|
| viewer | 허용 사이트 조회·설명·보고서·예제 분석·개인 분석 세션 초기화, 메모 분석·what-if |
| operator | viewer 권한과 허용 사이트 CSV 업로드 |
| admin | 전체 사이트, 모델·전역 산출물·모니터링·메타데이터; 공유 ingest는 별도 `HARBINGER_ALLOW_SHARED_INGEST=1`도 필요 |

사이트 목록·직접 URL·CSV 예제·분석·보고서·다운로드는 서버에서 제한한다. 복수 사이트 CSV는 하나라도 허용 목록 밖이면 거절한다. 전역 산출물과 `/metrics`, `/version`, `/ready`, OpenAPI는 관리자만 접근한다. 데이터가 없는 `/health` 및 정적 화면은 공개다. 사용자별 요청에는 사이트가 잘린 별도 Store와 캐시가 제공되고 전역 평가 수치는 제거된다. 업로드/예제 세션은 로그인 세션에 귀속되므로 다른 사용자가 분석 ID를 알아도 조회·다운로드·삭제하지 못한다. 같은 사용자의 새 로그인에도 이전 로그인 세션 ID를 재사용하지 않는다.

## 수명과 운영 한계

`HARBINGER_AUTH_TTL_SECONDS` 기본 1800(60–86400), `HARBINGER_AUTH_MAX_SESSIONS` 기본 256(1–2048). 서버 메모리에 만료 시각·CSRF 토큰·권한과 256비트 임의 쿠키 토큰을 보관한다. 로그아웃·만료는 연관 분석 세션도 삭제한다. 요청 시 검사와 60초 청소 주기를 함께 사용한다. 5분에 IP별·사용자 이름별 로그인 시도 10회로 제한하며 추적 키는 최대 2048개다. 프록시의 전달 IP 헤더를 믿지 않으므로 동일 프록시 뒤 사용자는 IP 한도를 공유한다. 대규모 서비스용 인증 제공자나 지속 세션 저장소는 구현하지 않았다.

반드시 **단일 worker**로 실행한다. 재시작 시 세션이 사라지며 다중 worker/서버 간 공유는 지원하지 않는다. MFA, 외부 IdP, 자동 계정 복구는 없다. 역할/계정 변경은 파일 수정 후 재시작한다. 전역 모델은 합성 데이터로 학습된 공용 번들이며 고객별 비공개 학습 모델 공유의 안전성을 주장하지 않는다.

## 재현 가능한 로컬 검사

임시 계정 생성기는 임의 암호를 `/tmp/harbinger-protected-*`의 0600 파일에 저장한다. 테스트 종료 후 두 파일과 디렉터리를 삭제한다. 실사용 계정으로 배포하지 않는다.

```sh
PYTHONPATH=src python scripts/protected_fixture.py --site S01 --site S02
# 출력된 경로를 사용한다. 기존 모델/자료 경로는 평소와 동일하게 지정한다.
export HARBINGER_AUTH_USERS_FILE=/tmp/harbinger-protected-REPLACE/users.json
export HARBINGER_PROTECTED_MODE=1
export HARBINGER_AUTH_ORIGIN=http://127.0.0.1:8765
export HARBINGER_AUTH_COOKIE_SECURE=false  # 로컬 HTTP 검사에만 명시적으로 허용
PYTHONPATH=src uvicorn harbinger.api.main:app --host 127.0.0.1 --port 8765 --workers 1 --no-access-log
# 다른 터미널
PYTHONPATH=src python scripts/verify_protected.py http://127.0.0.1:8765 --credentials /tmp/harbinger-protected-REPLACE/credentials.json
OMP_NUM_THREADS=1 PYTHONPATH=src:. pytest tests/test_protected_auth.py tests/test_workbench.py tests/test_api.py
```

브라우저에서는 `/console/login.html`로 접속해 임시 계정으로 로그인하고 고객사 선택, 예제 분석, 다운로드, 로그아웃을 확인한다. 두 브라우저 컨텍스트에서 서로 다른 계정을 사용하면 분석 세션 소유권 거부도 검사할 수 있다. 자동 도구 검사는 실제 고객 또는 참가자의 사용성 평가가 아니다.

## Prometheus 전용 읽기 토큰 (선택)

`HARBINGER_AUTH_METRICS_TOKEN`을 설정하면 **GET `/metrics`에만** `Authorization: Bearer ...` 인증을 추가로 허용한다. 비어 있으면 관리자 로그인만 허용한다. 토큰은 32–256 ASCII 문자이며 `secrets.token_urlsafe(32)`로 오프라인 생성한 고엔트로피 값을 사용한다. 자동 기본값은 없다. 이 값은 SecretStr로 감추며 다른 `/v1`·관리자 API·변경 요청에는 권한을 주지 않는다. TLS 및 Prometheus `authorization.credentials_file`로 전달하고 저장소·명령 출력·로그에 남기지 않는다. 교체 후 재시작하면 이전 토큰은 무효다.
