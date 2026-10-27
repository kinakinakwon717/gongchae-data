# 오늘의 공채 데이터

접수 중인 공공 채용공고를 하루 두 번(오전·오후 5시 17분) 받아 `docs/jobs.json`에 저장합니다.

- 잡알리오(재정경제부 공공기관 채용정보 조회서비스): 공공기관·공기업
- 고의24 채용정보 API: 공무직 (기업형태 공공기관 + 무기계약, '공무직' 키워드)

## 처음 한 번만
1. Settings > Secrets and variables > Actions > New repository secret 에 두 개 등록
   - `JOB_API_KEY` : 공공데이터포털 일반 인증키(Decoding)
   - `WORK24_API_KEY` : 고의24 Open API 인증키
2. Actions 탭 > 공고 업데이트 > Run workflow 로 첫 실행

한쪽 키만 있어도 그쪽 공고는 저장됩니다.
블로거 테마는 `https://raw.githubusercontent.com/<아이디>/gongchae-data/main/docs/jobs.json` 을 읽습니다.
