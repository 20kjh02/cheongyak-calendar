# 청약 캘린더 (LH 임대 · 서울/경기/인천)

매일 아침 7시(한국 시간)에 LH 임대 공고를 수집해 캘린더 페이지를 갱신하고,
**접수 시작 하루 전**에 이메일로 알려줍니다.

- 캘린더: https://20kjh02.github.io/cheongyak-calendar/
- 1단계 범위: LH 임대주택 (SH, 청년안심주택은 2단계)

## 설정 순서

### 1. 파일 올리기
저장소 `20kjh02/cheongyak-calendar` 에서 **Add file → Upload files** 로 아래 3개를 올리고 **Commit changes**.
- `fetch_notices.py`
- `template.html`
- `README.md`

### 2. 자동 실행 파일 만들기
점(.)으로 시작하는 폴더는 업로드가 잘 안 될 수 있어서 직접 만드는 게 안전해요.
1. **Add file → Create new file**
2. 파일 이름 칸에 `.github/workflows/run.yml` 입력 (슬래시를 치면 폴더가 자동으로 만들어져요)
3. 함께 받은 `run.yml` 내용을 그대로 붙여넣고 **Commit changes**

### 3. Secrets 등록
**Settings → Secrets and variables → Actions → New repository secret** 에서 4개를 하나씩 등록.

| 이름 | 값 |
|---|---|
| `LH_API_KEY` | 공공데이터포털 **일반 인증키(Decoding)** |
| `GMAIL_USER` | 알림을 보낼 Gmail 주소 |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 16자리 |
| `MAIL_TO` | 알림을 받을 이메일 주소 |

### 4. 쓰기 권한 켜기
**Settings → Actions → General → Workflow permissions → Read and write permissions** 선택 후 Save.
(수집한 데이터와 캘린더 페이지를 저장소에 저장하려면 필요해요.)

### 5. 첫 실행 (테스트)
1. **Actions** 탭 → **청약 알림** → **Run workflow**
2. `테스트 메일 발송`, `API 응답 원문 저장` 두 칸을 **모두 체크**하고 실행
3. 1~2분 뒤 초록 체크가 뜨면 성공. 테스트 메일이 도착했는지 확인
   (안 보이면 스팸함 확인)

### 6. 캘린더 주소 켜기
**Settings → Pages → Build and deployment**
- Source: **Deploy from a branch**
- Branch: **main** / 폴더: **/docs** → Save

몇 분 뒤 위 캘린더 주소가 열립니다.

## 이후 동작
- 매일 07:00 자동 실행, 새 공고 반영
- 접수 시작일이 오늘~내일인 공고가 있으면 이메일 발송 (공고당 1회)
- 접수 시작일을 못 읽은 신규 공고는 "일정 확인 필요"로 1회 안내

## 문제가 생기면
- **Actions 실행 로그**의 빨간 줄 내용을 알려주세요. (인증키는 로그에 표시되지 않아요)
- 접수 시작일이 계속 "확인 필요"로 나오면, 5번에서 저장된 `data/debug/` 폴더의 파일
  (`list_*.txt`, `detail.txt`)을 보여주세요. 응답 필드 이름에 맞춰 코드를 조정하면 됩니다.
- 3개월 이상 저장소에 변경이 없으면 GitHub가 자동 실행을 멈출 수 있는데,
  이 프로젝트는 매일 갱신 내용이 저장되어 보통 해당되지 않아요.

## 주의
- 접수 일정은 참고용입니다. 신청 전 반드시 LH 청약플러스의 공고문 원문을 확인하세요.
- 인증키와 앱 비밀번호는 코드나 채팅에 적지 말고 Secrets에만 넣으세요.
