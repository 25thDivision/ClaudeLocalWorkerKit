# 메인 계정 선택

메인 세션을 어느 계정으로 띄울지 시작할 때 고르는 기능이다. `claude-duo`, `codex-duo`, `claude-main`, `codex-main`,
`claude-duo --manual`에 적용된다. 워커는 등록한 LLM 서버를 쓰므로 이 선택과 무관하다.

계정을 등록하지 않으면 아무것도 묻지 않고 이전과 똑같이 동작한다.

## 등록

```bash
llm-account init        # <설정 디렉터리>/accounts.json 생성
llm-account list        # 계정별 Claude 로그인과 Codex 활성 키
```

`init`이 만드는 예시는 개인 계정과 팀 계정 두 개다. 이름과 개수는 파일을 직접 고쳐 바꾼다.
비밀 값은 이 파일에 넣지 않는다.

```json
{"accounts": {
  "INDIVIDUAL": {"label": "Personal", "aliases": ["personal", "indiv"], "claude_config_dir": ""},
  "TEAM": {"label": "Team", "aliases": [], "claude_config_dir": "~/.claude-team"}
}}
```

| 필드 | 뜻 |
|---|---|
| 이름 | 대문자 식별자. `--account` 값과 API 키 변수명 접미사에 쓴다 |
| `label` | 선택 항목. 메뉴, 상태 표시줄, 터미널 제목에 보이는 글자. 없으면 이름을 쓴다. `--account`에도 쓸 수 있다 |
| `aliases` | `--account`에 쓸 수 있는 다른 이름. 대소문자는 구분하지 않는다 |
| `claude_config_dir` | 이 계정의 Claude 설정 디렉터리. 비우면 기본 `~/.claude` |
| `codex_key` | 선택 항목. OpenCodex 키 라벨이 계정 이름과 다를 때 적는다 |

## 고르는 방법

```bash
claude-duo --account team
codex-duo --account personal
claude-duo                      # 터미널이면 번호 메뉴로 묻는다
```

묻지 않는 경우는 세 가지다.

- `accounts.json`이 없을 때
- 터미널이 아닌 실행에서 `--account`가 없을 때. 현재 계정 그대로 띄운다
- `claude-duo --manual`이 이미 떠 있는 tmux 세션에 다시 붙을 때

등록되지 않은 이름을 주면 메인을 띄우지 않고 종료한다.

## Claude 메인

계정마다 Claude 설정 디렉터리를 따로 쓴다. Claude Code가 여러 계정용으로 안내하는 `CLAUDE_CONFIG_DIR` 방식이며
로그인, claude.ai 커넥터, Remote Control이 계정별로 온전히 동작한다.

```bash
llm-account link TEAM                                # 디렉터리 생성
CLAUDE_CONFIG_DIR=~/.claude-team claude auth login   # 그 계정으로 한 번 로그인
```

디렉터리가 없는 계정을 고르면 실행기가 만들지 물어본다. `link`가 하는 일은 다음과 같다.

| 항목 | 처리 | 이유 |
|---|---|---|
| `CLAUDE.md` | `~/.claude`로 링크 | 전역 지침을 한 곳에서 관리 |
| `projects/` | `~/.claude`로 링크 | 메모리와 세션 기록(`--resume`)을 계정 간 공유 |
| `settings.json` | 복사 | Claude Code가 파일을 다시 쓰므로 링크하지 않는다 |
| 로그인, `.claude.json`, `plugins/`, `skills/` | 건드리지 않음 | 계정에 묶인 상태 |

복사한 `settings.json`은 이후 자동으로 맞춰지지 않는다. 한쪽에서 바꾼 설정은 다른 쪽에 직접 반영한다.
새 디렉터리로 처음 띄우면 테마 선택과 폴더 신뢰 확인이 한 번 더 나온다.

계정 디렉터리는 메인 프로세스에만 지정한다. 워커와 풀은 기존 환경 그대로 실행된다.

## Codex 메인

Codex 메인이 [OpenCodex 경유 Anthropic API 키](CODEX_ANTHROPIC.md)를 쓸 때, 계정은 `anthropic-apikey` 공급자의 키 풀에서
활성 키를 바꾸는 것으로 선택된다. 실행기가 `ocx account use anthropic-apikey <키 ID>`를 대신 실행한다.

키와 계정은 라벨로 연결한다. 아래 둘 중 하나에 해당하는 키가 그 계정의 키다.

- `${ANTHROPIC_API_KEY_<계정 이름>}` 참조로 등록한 키
- `ocx account add-key anthropic-apikey --label <계정 이름>`으로 넣은 키

두 번째 방식에서도 키 값 대신 `${변수}` 문자열을 stdin으로 넣으면 참조로 저장되어 설정 파일에 키가 남지 않는다.

```bash
printf %s '${ANTHROPIC_API_KEY_TEAM}' | ocx account add-key anthropic-apikey --label TEAM
```

`add-key`는 추가한 키를 바로 활성으로 만든다. 추가한 뒤 원하는 계정으로 다시 전환한다.

`codex-bootstrap`의 기본 변수명 `ANTHROPIC_API_KEY_INDIVIDUAL`, `ANTHROPIC_API_KEY_TEAM`은 이 규칙에 맞춰져 있다.

활성 키는 프록시 전체에 하나다. 다음 두 가지를 알고 써야 한다.

- 한 세션에서 계정을 바꾸면 실행 중인 다른 Codex 세션도 다음 요청부터 그 키를 쓴다
- 세션 도중 바꾸려면 다른 터미널에서 `ocx account use anthropic-apikey <키 ID>`를 직접 실행한다. 키 ID는 `ocx account list anthropic-apikey`에 나온다

키 전환에 실패하면 Codex를 띄우지 않고 종료한다.

## 화면 표시

| 메인 | 표시 위치 | 내용 |
|---|---|---|
| Claude | 입력창 아래 상태 표시줄 | 계정 표시 이름과 로그인 이메일. 예 `Team · you@example.org` |
| Codex | 시작 직전 한 줄과 터미널 제목 | `Account: Team`, `codex [Team]` |
| Codex `--panes` | 키트가 만든 tmux 세션의 상태 줄 | 현재 활성 키의 계정 |

- Claude 표시는 시작할 때 `claude auth status`가 알려 준 값이다. 세션 안에서 `/login`으로 계정을 바꾸면 표시와 달라진다
- Codex의 시작 줄과 제목도 시작 시점 값이다. 다른 곳에서 활성 키를 바꿔도 따라가지 않는다. `--panes` 세션의 상태 줄과 `llm-account current`는 현재 값을 읽는다
- Codex는 기본적으로 터미널 제목을 프로젝트 이름으로 바꾼다. 계정을 고른 세션에서는 `tui.terminal_title=[]`로 이를 끄고 실행기가 쓴 제목을 유지한다. tmux는 기본 상태 줄에 창 제목 앞 21자를 보여 준다
- `claude-main`에 `--settings`를 직접 넘기면 계정 상태 표시줄은 붙이지 않는다
- 표시되는 글자를 바꾸려면 `accounts.json`의 `label`만 고친다. 다음에 띄우는 세션부터 적용되며 디렉터리나 키 연결에는 영향이 없다

## 확인된 버전

Claude Code 2.1.311, Codex CLI 0.167.0, OpenCodex 2.99.0, tmux 3.4.
