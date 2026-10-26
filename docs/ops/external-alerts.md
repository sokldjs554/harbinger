# 운영자 이메일 경보 연결·통제 시험

운영자는 프로젝트 소유자이며 이메일 수신을 선택했다. 실제 주소는 GitHub Secret에만 등록한다. **설정·발송 성공·운영자의 실제 수신 확인은 서로 다른 단계**다. 이 문서와 빈 기록지는 수신 완료 증거가 아니다.

## 비밀값 등록

[저장소 Settings → Secrets and variables → Actions](https://github.com/sokldjs554/harbinger/settings/secrets/actions)의 **New repository secret**에 아래 이름으로 등록한다. 채팅·커밋·PR 본문에 값을 붙이지 않는다.

| 이름 | 값 |
|---|---|
| `HARBINGER_SMTP_HOST` | 발송 SMTP 호스트. 네이버 발송 계정은 `smtp.naver.com` |
| `HARBINGER_SMTP_PORT` | 지원 경로는 `465` / 연결 시작부터 SSL/TLS |
| `HARBINGER_SMTP_USERNAME` | 메일 서비스가 지정한 발송 계정 로그인 ID |
| `HARBINGER_SMTP_PASSWORD` | SMTP용 앱 비밀번호. 일반 로그인 비밀번호를 사용하지 않음 |
| `HARBINGER_SMTP_FROM` | 발송 계정이 사용하도록 허용한 메일 주소 |
| `HARBINGER_ALERT_TO` | 실제 운영자 수신 주소 한 개 |

네이버는 [공식 IMAP/SMTP 안내](https://help.naver.com/service/30029/contents/21344)의 사용 설정과 2단계 인증·앱 비밀번호를 따른다. [비밀번호 정책 FAQ](https://help.naver.com/service/30029/contents/24347). SMTP 제공자 정책과 인증·해외 접속 허용 여부에 따라 전송이 거절될 수 있으며, 설정만으로 발송 성공을 보장하지 않는다. SSL 465와 [Alertmanager 0.33의 implicit TLS 설정](https://prometheus.io/docs/alerting/0.33/configuration/#email_config)을 사용한다. 이 구현은 사용자가 설정한 SSL 465를 지원하며 평문·TLS 검증 해제는 지원하지 않는다.

기존 AWS Actions 비밀값과 검증된 EC2 SSH 신원은 재사용한다. 새 인스턴스·볼륨·유료 메일 서비스를 만들지 않는다. 기존 메일 계정 정책 범위에서 발송하며 유료 제공자 추가가 필요하면 실행 전에 용도·비용을 별도 확인한다.

## 연결 구조와 자원

기존 EC2의 API `/metrics` → Prometheus → Alertmanager → 인증된 SMTP → 운영자 메일함으로 연결한다. 기존 API·모델을 재학습하거나 재시작하지 않는 별도 Compose 프로젝트다. 모니터링과 알림의 버전은 서비스 학습 소스와 별도로 기록한다.

- Prometheus: 15초 수집/평가, 최대 CPU 0.25·메모리 192MiB, 시계열 24시간/100MB 제한.
- Alertmanager: 최대 CPU 0.1·메모리 64MiB, v0.33.0의 `smtp_force_implicit_tls=true`로 연결 시작부터 TLS를 강제하고, 동일 경보 반복 간격 12시간, 복구 알림 활성화.
- 두 HTTP 관리 주소는 `127.0.0.1`에만 열고 외부 방화벽 포트를 추가하지 않는다. SMTP 비밀번호는 읽기 전용 파일·제한된 소유권으로 마운트한다. 로그에는 계정 정보가 남을 수 있으므로 전체 디버그 로그를 공개 산출물로 올리지 않는다.
- 위 값은 **컨테이너 제한**이다. 인스턴스 사양이나 실측 사용량·처리량 보장이 아니다. 기존 서버와 같은 장애 영역이므로 서버 전체가 꺼지면 이 경로도 멈춘다. 외부 독립 감시·고가용성·장기 운영 SLA는 검증 범위 밖이다.

## 통제된 시험 절차

1. main의 전체 CI 성공과 비밀값 설정을 확인한 뒤 **Existing AWS operator email verification** workflow를 수동 실행한다. 같은 배포 동시 실행 그룹을 사용한다.
2. 기존 계정·지역·프로젝트 태그·실행 중 인스턴스·SSH 신원을 검증한다. 서버 생성/기동은 하지 않고 실행 중인 기존 서버만 허용한다. SSH는 실행기의 단일 IP에만 잠시 허용하고 종료 시 제거한다.
3. 공개 서비스의 모델 버전과 health를 기록한다. 별도 `127.0.0.1:19101` 시험 대상의 정상 수집을 확인한 뒤 그 시험 대상만 중단한다. 실제 서비스나 모델을 중단하지 않는다.
4. 실제 Prometheus `up==0`이 30초 지속되어 `HarbingerControlledNotification`이 발화하는 것을 관측한다. `mail-<run-id>-<attempt>` 시험 번호가 이메일 제목에 포함된다. Alertmanager의 해당 시험 수신 경로 `Notify success` 기록을 확인하되 이를 받은편지함 도착으로 단정하지 않는다.
5. 시험 대상을 복구하고 rule이 inactive가 되는 것과 같은 경로의 복구 이메일 전송 성공 기록을 확인한다. 운영자는 실제 받은편지함/스팸함에서 두 메일의 시험 번호·상태·수신 시간을 확인한다.
6. 시험 rule·scrape 대상을 제거하고 임시 HTTP 서버를 종료한다. 실제 API health·모델 버전 유지·남은 firing 경보·SSH 정리를 기록한다. 시험 경로는 해제하고 정상 운영 규칙과 이메일 경로는 유지한다. 설정/시험 실패 시 이전 모니터링 구성을 복구하거나 처음 설치한 모니터링 프로젝트만 중단한다.

운영자 회신에는 메일 원문·주소·앱 비밀번호를 공개할 필요가 없다. **시험 번호, 장애/복구 각각의 제목과 실제 수신 시각(시간대 포함), 받은편지함 또는 스팸함, 미수신 여부**를 알려주면 된다. 미수신은 미수신으로 남기고 재시도에는 새 실행 번호를 사용한다.

## 기록과 판정

workflow 산출물 `operator-email-verification`의 `result.json`은 fault/복구 조작 시각, rule 상태를 처음 관측한 시각, 이메일 전송 성공 로그 시각, 시험 종료 상태를 담는다. polling 관측 시각을 정확한 장애 발생 순간이나 사용자가 메일을 연 시각으로 바꾸지 않는다. `operator_receipt_confirmed=false`는 사람이 회신하기 전까지 유지한다.

| 항목 | 실제 결과 |
|---|---|
| workflow URL / 모니터링 소스 / 시험 번호 | 미실행 |
| 서비스 소스 / 모델 버전 전후 | 미확인 |
| 장애 주입 / firing 최초 관측 시각 | 미확인 |
| 장애 이메일 전송 성공 / 운영자 실제 수신 시각 | 미확인 / 미확인 |
| 시험 대상 복구 / inactive 최초 관측 시각 | 미확인 |
| 복구 이메일 전송 성공 / 운영자 실제 수신 시각 | 미확인 / 미확인 |
| 실제 메일함 종류 / 같은 시험 번호 대조 | 미확인 |
| 시험 제거 / 정상 health / 모델 유지 / 남은 경보 / SSH 정리 | 미확인 |
| 운영자 확인 날짜·결과·미수신 이유 | 실제 회신 대기 |

전체 완료는 전송 성공만으로 판정하지 않는다. 두 실제 수신, rule 복구, 시험 제거, 정상 서비스 상태와 SSH 정리를 모두 확인해야 한다. 기존 로컬 프로토콜 수신기·자동 SMTP 시험은 별도의 개발 검증이며 이 표에 실제 운영자 수신으로 옮기지 않는다.
