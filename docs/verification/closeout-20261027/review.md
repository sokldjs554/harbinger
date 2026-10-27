# 후속 변경 독립 검토와 수정

검토 대상은 PR #16 병합 커밋부터 d25b84c까지의 전체 변경이다. 별도 읽기 전용 검토에서 Critical 0건, Important 1건과 문구 정확성 1건을 확인했다.

- Important: EXIT 정리 함수가 `set -e`를 상속하여 Docker 롤백 실패 시 신규 SMTP 비밀 파일 삭제를 건너뛸 수 있었다. 실제 셸 함수를 추출하고 Docker가 실패하게 하는 회귀 검사에서 첫 설치·기존 설치 모두 실패를 재현했다. 정리 함수에서 오류 후에도 삭제를 계속 시도하고 실패 상태를 보존하도록 수정했다. [수정 전](checks/rollback-red.txt), [수정 후](checks/rollback-green.txt).
- 로컬 SSL 수신 시험 JSON에 운영 호스트 범위 문구가 남아 있었다. 도구가 로컬 수신·외부 미발송 범위를 명시하도록 수정했다. 이전 원본은 보존하며 새 실행은 `mail-final-*` 기록으로 구분한다.

검토는 운영 Docker 실행, 네이버 SMTP 인증·전송, 운영자 받은편지함 수신을 증명하지 않는다. 이 항목은 실제 workflow와 운영자 회신으로 따로 확인한다. 강제 실행 취소 중 원격 정리까지 검증한 것은 아니다.

## 실제 첫 외부 시험 후 후속 검토

첫 외부 시험의 결과 업로드 누락과 SMTP 실패 분류·이전 결과 보존 변경을 별도로 검토했다. Important 1건: 이전 결과를 가져오는 SSH 실패를 파일 부재와 구분하지 않아 다음 실행이 원본을 덮어쓸 수 있었다. 명시적 파일 부재 코드(44)만 허용하고 SSH/권한/읽기 오류는 설치 전에 중단하도록 수정했다. [실패 재현](checks/previous-read-red.txt), [수정 후](checks/previous-read-green.txt). 후속 검토에서 이외의 material finding은 없었다.

[로컬 SMTP 535 거절 검사](checks/mail-rejection-result.json)는 실제 SSL 연결·인증 거절·경보 정리와 비밀값 제외를 확인한다. 이 535 코드는 로컬 수신기가 의도적으로 반환한 값이며 실제 네이버 응답으로 표현하지 않는다.

후속 최종 코드의 [전체 테스트](checks/full-tests-notification-final.txt)는 TensorFlow 포함 378개 통과, 경고 8개다. 관련 경계·실패 처리 검사는 20개다. 이 통과를 실제 네이버 수신으로 대체하지 않는다.

## 첫 설치 실패 뒤 설정 보존 결함

PR #19 병합 후 지속성을 추가 점검하면서 `readlink -f`가 존재하지 않는 마지막 경로를 반환하는 결함을 재현했다. 첫 실패 뒤 `current` 링크가 없는 상태에서 재설치하면 이전 경로가 `root/current`로 저장되고, 새 링크 생성 후 이전 비밀 파일 정리가 새 활성 설정을 삭제할 수 있었다. 실제 설치 스크립트의 대입·정리 부분을 실행하는 [실패 재현](checks/current-link-red.txt)과 [수정 후 검사](checks/current-link-green.txt)를 보존한다.

존재하는 대상만 해석하는 `readlink -e`와 대상 동일성 검사를 적용했다. 실제 SMTP 확인 뒤 모니터링 컨테이너만 재생성하여 설정 로드·API 수집·정상 상태를 검사하고, 링크 교체와 이전 파일 정리 후 새 활성 파일 보존도 별도 기록한다. 비밀 파일 내용은 읽거나 출력하지 않고 존재 여부만 공개한다. 추가 읽기 전용 독립 검토에서 material finding은 없었으며 [관련 검사 24개](checks/persistence-focused.txt)가 통과했다. 이 로컬 검사는 실제 운영 재기동 증거를 대신하지 않는다. 운영 결과는 [후속 실행 원본](external-alerts/persistence-result.json)에 남겼다. 이전 활성 파일 부재와 수정 후 재생성·최종 파일 보존을 실제 확인했다.

수정 후 [전체 검사](checks/full-tests-persistence.txt)는 TensorFlow를 포함해 382개 통과, 경고 8개다. Ruff·셸 구문·문서 수치·릴리스 해시·기존 공개 운영 비교 검증도 통과했다.
