# 2026-11-17 AWS 근거 확인

조사 SHA: `7daa95603d7dc7235135933b8ff18113c8133128`. 이번 작업은 Codex의 문서·근거 확인이다.

```bash
python -m pytest -o addopts='' -q tests/test_aws_deploy.py
```

Linux·Python 3.12.14에서 **34개 통과, 0.06초**. [전체 로그](harbinger-aws-tests-explicit.log). 실제 클라우드 리소스를 생성하거나 배포하지 않는 경계 검사다.

[공개 HTTP 확인](public-http.json)에서 Harbinger 진입 Pages는 200이지만 AWS IP의 health는 TLS 이름 검증 오류로 확인하지 못했다. 인증서 검증을 끄지 않았다. 기존 [AWS 배포·재부팅·갱신 시험 결과](../closeout-20261027/release/aws/deployment-result.json), [운영 알림과 수신 기록](../closeout-20261027/README.md)은 과거 시점의 증거다.

README의 근거 안내 링크와 [클라우드 운영 근거](../../cloud-operations-evidence.md)만 추가했다. 제품·모델·배포 스크립트·방화벽·인증서·알림 설정은 변경하지 않았다. [증거 파일 해시](sha256.json).
