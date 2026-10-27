# PR #20 개발 검증 원본

[CI 40425947730](https://github.com/sokldjs554/harbinger/actions/runs/40425947730)의 test·tensorflow·image가 모두 통과했다. 검사 소스는 `4a0e654304d8ee688a8c262804e97ae435c36189`, 동일 파일 트리의 병합 커밋은 `c5df2df8943ec5759626a71909ad822bc1baa6cb`다. [산출물 출처와 원본 SHA-256](manifest.json)을 보존한다.

- `browser-checks-checks.json`: 실제 모델 API의 CSV 계산, 오류 입력 보존, 3종 다운로드, 모바일 필터·화면 이동·상태 복원.
- `static-mobile-checks.json`: 저장 결과 모드의 화면과 모바일 조작. 새 모델 계산으로 표현하지 않는다.
- `energy-browser-checks.json`: 실제 로컬 API에서 자료 없음·관측 부족·정상 계산, 모바일 화면.
- `protected-checks-checks.json`: 계정·고객사·세션 범위 제한.
- `operator-email-local-result.json`: 실제 로컬 SSL SMTP 정상 전송. 외부 네이버나 사람 수신 증거가 아니다.
- `operator-email-rejected-result.json`: 로컬 수신기가 의도적으로 반환한 535 인증 거절과 정리. 실제 네이버 장애 원인으로 해석하지 않는다.
- `docker-api.json`, `docker-image.json`: 비루트 UID 10001·소스 파일 80개 해시, 실제 컨테이너 API·업로드·다운로드·에너지 보류.
- `retest-recorder-checks.json`: 기록 도구의 자동 조작만 확인했다. 사람의 과업 재측정 자료가 아니다.

모델 `v20261027-003704`와 이 폴더의 수치는 CI가 만든 합성 검사 모델의 결과이며 공개 AWS `v20261026-151241`·Pages `v20261026-093937`를 교체하지 않는다. 장기 안정성·고객 실증·AWS 처리량 검증을 뜻하지 않는다. 화면 구현은 변경하지 않아 새 디자인 전후 캡처 비교 대상은 없다. 실제 브라우저 캡처는 위 CI의 `browser-verification` 산출물에 포함된다.
