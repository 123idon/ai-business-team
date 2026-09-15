# AI 사무실 v1.1

이 폴더가 실제 설치본입니다. Python 표준 라이브러리만 사용하며 모델 API 키·유료 서버가 필요하지 않습니다.
현재 Windows 네이티브 환경에서 실행합니다. WSL 설치와 Ubuntu 사용자 초기화 완료 후 같은 소스와 공통 자료를 옮길 수 있습니다. CLI 로그인은 Ubuntu에서 각각 다시 수행하며 토큰을 복사하지 않습니다.

## 시작

- `대시보드.cmd`를 더블클릭하면 로컬 읽기 전용 화면을 엽니다.
- `업무관리.cmd`를 더블클릭하면 이 폴더의 터미널을 엽니다.
- 터미널에서 `python office.py doctor`로 구독 로그인 상태를 확인합니다.
- `python office.py add "업무 제목" "구체적인 요청과 완료 기준" --role CEO`로 업무를 등록합니다.
- 반환된 업무 ID로 `python office.py run 업무ID`를 실행합니다. 중요 업무는 별도 Codex 검수를 거칩니다.
- `python office.py status`로 상태를 확인합니다. 산출물은 `runs/실행ID/artifact.md`에 저장됩니다.
- `python office.py retry 업무ID`는 기록을 확인한 후 명시적으로 재시도 준비합니다. 이어서 run을 실행합니다.

## 공통 기억과 기록

`company/`의 헌장·역할·절차가 공통 원본입니다. `data/office.sqlite3`가 업무 원장입니다.
`python office.py memory "확인할 가정" --tags "시장 검증"`으로 기억을 추가합니다.
`python office.py search "시장검증"`으로 검색합니다. FTS5와 띄어쓰기 보완, 일부 동의어를 사용합니다.
`python office.py import 자료.md`는 출처를 미확인 자료로 등록하고 SHA256을 기록합니다.
기존 회의록에 있는 통계·사업 판단을 검증된 사실로 자동 승격하지 않습니다.

## 중단·복구

`python office.py stop`은 새 작업을 차단합니다. 실행 중 작업 취소는 해당 실행 터미널에서 Ctrl+C를 사용합니다.
`python office.py recover`는 중단된 RUNNING 업무를 WAITING_EXTERNAL로 옮깁니다. 외부 행동을 자동 재실행하지 않습니다.
`python office.py resume`은 새 작업 차단만 해제합니다.
`python office.py backup`은 SQLite 일관성 있는 백업과 공통 파일·산출물을 ZIP으로 보관합니다.
`python office.py restore-copy backups/백업.zip 새폴더`로 별도 폴더에 복원하고 원장·산출물 해시를 검사합니다.
복원 대상은 존재하지 않는 폴더여야 합니다. 현재 운영본은 덮어쓰지 않습니다.

## GPT 단독 전환

실제로 원하는 구독에 가입한 뒤 `python office.py switch codex_cli`를 실행합니다.
원장·기억·미완료 업무를 그대로 두고 주 실행자와 검수자가 별도 Codex 세션을 사용합니다.
구독 가입·결제·Claude 해지는 이 프로그램이 수행하지 않습니다.
현재로 돌아갈 때는 `python office.py switch claude_code`를 사용하되 Claude 구독이 유효해야 합니다.

## 운영 범위와 남은 보안 작업

초기 어댑터는 제공한 자료에서 문서를 작성합니다. Claude의 도구를 비활성화하고 사용자 설정·MCP를 제외합니다. Codex는 사용자 설정을 제외한 read-only 실행과 shell tool 비활성화를 사용합니다.
업무 관리자가 결과를 검사하고 파일을 저장합니다. 모델의 JSON PASS는 사람의 승인이 아닙니다. 외부 발송·결제·공개 배포 기능이 없습니다.
개별 Windows 사용자·관리자 서비스로 분리된 완전한 보안 경계는 아직 없습니다. 외부 실행을 붙이기 전에 별도로 구축해야 합니다.
기준 섹션·출처 ID·해시·검수를 통과한 DONE은 문서 과제의 완료이며, 사실 정확성 또는 사업 성공을 보장하지 않습니다.
오전 9시에는 CEO 계획 1건과 기존 READY 업무 최대 1건을 순차 실행합니다. 오후 6시에는 모델 호출 없이 로컬 마감 보고를 만듭니다. 로그인한 사용자 환경에서만 실행하며 PC 절전/종료 중에는 작동하지 않습니다. 설정의 automatic_execution을 false로 바꾸면 아침도 로컬 보고만 생성합니다.
일일 실행 ID를 원장에 먼저 기록해 같은 날 재호출을 막습니다. 한도 대기·로그인 필요·실행 중 업무가 있으면 새 일일 실행을 멈춥니다. 사용량 제한·로그인 실패 시 자동 유료 전환을 하지 않습니다.
Notion은 표시용이며 로컬 원장을 대신하지 않습니다. 브라우저 연동과 무인 동기화는 다릅니다.

## 검증

`python -m unittest discover -s tests -v`

`python office.py improvement 업무ID`는 실제 초안과 수정본의 검수 결과를 비교해 개선 후보를 기록합니다. 하나의 업무에서 통과율이 개선됐다는 사실을 전체 품질 향상으로 일반화하지 않습니다. 자동 승격은 구현하지 않았으며 기존 절차는 유지합니다. 별도 업무 품질 평가 집합과 권한 분리 기반 승격은 후속 단계입니다.

공식 문서: https://code.claude.com/docs/en/headless · https://code.claude.com/docs/en/authentication · https://learn.chatgpt.com/docs/auth · https://learn.chatgpt.com/docs/non-interactive-mode
