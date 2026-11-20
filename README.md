청약 캘린더 (LH 임대 · 서울/경기/인천)

매일 아침 7시(한국 시간)에 LH 임대 공고를 수집해 캘린더 페이지를 갱신하고, 접수 시작 하루 전에 이메일로 알려줍니다.

캘린더: https://20kjh02.github.io/cheongyak-calendar/
수집 범위: LH 임대주택(서울·경기·인천), SH 공공임대(서울), 청년안심주택(서울시 공식 사이트, 최초·추가·신규 모집 전체)
설정 순서
1. 파일 올리기

저장소 20kjh02/cheongyak-calendar 에서 Add file → Upload files 로 아래 3개를 올리고 Commit changes.

fetch_notices.py
sh_notices.py (SH 수집용)
youth_notices.py (청년안심주택 수집용)
template.html
README.md
2. 자동 실행 파일 만들기

점(.)으로 시작하는 폴더는 업로드가 잘 안 될 수 있어서 직접 만드는 게 안전해요.

Add file → Create new file
파일 이름 칸에 .github/workflows/run.yml 입력 (슬래시를 치면 폴더가 자동으로 만들어져요)
함께 받은 run.yml 내용을 그대로 붙여넣고 Commit changes
3. Secrets 등록

Settings → Secrets and variables → Actions → New repository secret 에서 4개를 하나씩 등록.

이름	값
LH_API_KEY	공공데이터포털 일반 인증키(Decoding)
GMAIL_USER	알림을 보낼 Gmail 주소
GMAIL_APP_PASSWORD	Gmail 앱 비밀번호 16자리
MAIL_TO	알림을 받을 이메일 주소
3-1. 접수 일정용 API 추가 신청

접수 시작일은 별도 서비스에서 가져와요. 공공데이터포털에서 아래 서비스를 활용신청하세요 (자동승인).

한국토지주택공사_분양임대공고별 상세정보 조회 서비스
(이름이 비슷한 '공급정보 조회 서비스'와 다릅니다.)
4. 쓰기 권한 켜기

Settings → Actions → General → Workflow permissions → Read and write permissions 선택 후 Save. (수집한 데이터와 캘린더 페이지를 저장소에 저장하려면 필요해요.)

5. 첫 실행 (테스트)
Actions 탭 → 청약 알림 → Run workflow
테스트 메일 발송, API 응답 원문 저장 두 칸을 모두 체크하고 실행
1~2분 뒤 초록 체크가 뜨면 성공. 테스트 메일이 도착했는지 확인 (안 보이면 스팸함 확인)
6. 캘린더 주소 켜기

Settings → Pages → Build and deployment

Source: Deploy from a branch
Branch: main / 폴더: /docs → Save

몇 분 뒤 위 캘린더 주소가 열립니다.

SH 공고 수집 방식 (참고)
SH는 공식 공고 API가 확인되지 않아 서울주거포털(housing.seoul.go.kr)의 SH 공공임대 목록을 읽어요.
목록에는 접수 기간이 없어서 공고 상세 본문의 '신청기간' 글에서 날짜를 찾아요. 본문이 첨부파일이나 이미지뿐인 공고는 접수일이 "확인 필요"로 표시되고, 신규 공고 알림만 1회 와요.
사이트 구조가 바뀌면 sh_notices.py만 고치면 돼요. SH 수집이 실패해도 LH 수집과 알림은 계속 동작해요.
서버 부담을 줄이려고 목록 3쪽, 요청 사이 1초 대기, 접수일 확인은 실행당 최대 10건으로 제한했어요.
청년안심주택 수집 방식 (참고)
공식 사이트(soco.seoul.go.kr/youth)의 모집공고 목록은 자바스크립트로 채워져서 그대로 읽을 수 없어요. 대신 각 공고 상세 페이지의 '다음글' 링크를 따라가며 새 공고를 모아요. 마지막 확인 위치는 data/youth_state.json에 저장돼요.
접수 시작일은 상세 페이지의 '청약신청일', 종료일은 본문의 '청약신청 : ~' 구간에서 읽어요.
최초·추가·신규 모집 등 유형은 구분 없이 모두 수집하고, 유형 칸에 민간임대 추가모집 (마포구)처럼 표시해요.
[공공임대] 글은 SH 수집기가 이미 잡은 공고와 겹칠 수 있어, 게시일이 3일 이내로 비슷하면 건너뛰어요.
처음부터 다시 훑으려면 data/youth_state.json을 삭제하세요. 출발 공고 번호를 바꾸려면 youth_notices.py의 SEED_ID를 고치세요.
로그에 '마지막 공고가 ○○ 게시분입니다'가 나오면, 새 공고가 없는 것인지 연결이 끊긴 것인지 사이트에서 확인해 주세요.
이후 동작
매일 07:00 자동 실행, 새 공고 반영
접수 시작일이 오늘~내일인 공고가 있으면 이메일 발송 (공고당 1회)
접수 시작일을 못 읽은 신규 공고는 "일정 확인 필요"로 1회 안내
문제가 생기면
Actions 실행 로그의 빨간 줄 내용을 알려주세요. (인증키는 로그에 표시되지 않아요)
접수 시작일이 계속 "확인 필요"로 나오면, 5번에서 저장된 data/debug/ 폴더의 파일 (list_*.txt, detail.txt)을 보여주세요. 응답 필드 이름에 맞춰 코드를 조정하면 됩니다.
3개월 이상 저장소에 변경이 없으면 GitHub가 자동 실행을 멈출 수 있는데, 이 프로젝트는 매일 갱신 내용이 저장되어 보통 해당되지 않아요.
주의
접수 일정은 참고용입니다. 신청 전 반드시 LH 청약플러스의 공고문 원문을 확인하세요.
인증키와 앱 비밀번호는 코드나 채팅에 적지 말고 Secrets에만 넣으세요.
