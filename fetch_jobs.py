#!/usr/bin/env python3
"""접수 중인 공공 채용공고를 두 곳에서 받아 docs/jobs.json 으로 저장합니다.

1) 잡알리오 (재정경제부 공공기관 채용정보 조회서비스) - 공공기관·공기업
   환경변수 JOB_API_KEY  : 공공데이터포털 일반 인증키(Decoding)
2) 고용24 채용정보 API - 공무직 (기업형태 공공기관 + 무기계약, '공무직' 키워드)
   환경변수 WORK24_API_KEY : 고용24 Open API 인증키

표준 라이브러리만 사용합니다. 한쪽 키가 없으면 그쪽은 건너뜁니다.
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(ROOT, "docs")
OUT = os.path.join(DOCS, "jobs.json")
TODAY = datetime.now(KST).strftime("%Y-%m-%d")

ALIO_URL = "https://apis.data.go.kr/1051000/recruitment/list"
WORK24_URL = "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L01.do"

REGION_ALIAS = {
    "서울": "서울", "경기": "경기", "인천": "인천", "부산": "부산", "대구": "대구", "대전": "대전",
    "광주": "광주", "울산": "울산", "세종": "세종", "강원": "강원", "충북": "충북", "충청북": "충북",
    "충남": "충남", "충청남": "충남", "전북": "전북", "전라북": "전북", "전남": "전남", "전라남": "전남",
    "경북": "경북", "경상북": "경북", "경남": "경남", "경상남": "경남", "제주": "제주", "해외": "해외",
}


def get(url, params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "gongchae-bot"})
    with urllib.request.urlopen(req, timeout=40) as res:
        return res.read().decode("utf-8", errors="replace")


def pick(rec, *names):
    for n in names:
        v = rec.get(n)
        if v not in (None, "", []):
            return v
    return ""


def to_list(v):
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in str(v or "").split(",") if s.strip()]


def ymd(v):
    """20261030, 2026-10-30, 26-10-30, '채용시까지 26-10-30' 모두 2026-10-30 으로."""
    s = str(v or "")
    m = re.search(r"(20\d{2})[-./]?(\d{2})[-./]?(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"\b(\d{2})-(\d{2})-(\d{2})\b", s)
    if m:
        return f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def region_of(text):
    out = []
    for part in re.split(r"[,|/]", str(text or "")):
        part = part.strip()
        for k, v in REGION_ALIAS.items():
            if part.startswith(k) and v not in out:
                out.append(v)
                break
    return out


def save_sample(name, rec):
    with open(os.path.join(DOCS, name), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)


# ---------- 1) 잡알리오 ----------

def simple_emp(names):
    out = []
    for n in names:
        if "무기" in n:
            k = "무기계약직"
        elif "인턴" in n:
            k = "인턴"
        elif "정규" in n and "비정규" not in n:
            k = "정규직"
        else:
            k = "계약직"
        if k not in out:
            out.append(k)
    return out


def fetch_alio(key):
    records, page = [], 1
    while page <= 20:
        text = get(ALIO_URL, {"serviceKey": key, "resultType": "json", "numOfRows": 100,
                              "pageNo": page, "ongoingYn": "Y"})
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise RuntimeError("잡알리오 응답이 JSON이 아닙니다(인증키 확인): " + text[:300])
        if str(data.get("resultCode")) != "200":
            raise RuntimeError(f"잡알리오 오류 {data.get('resultCode')}: {data.get('resultMsg')}")
        batch = data.get("result") or []
        records.extend(batch)
        if not batch or len(records) >= int(data.get("totalCount") or 0):
            break
        page += 1
    if records:
        save_sample("sample_alio.json", records[0])

    jobs = []
    for r in records:
        sn = pick(r, "recrutPblntSn", "pblntSn", "recrutPbancSn")
        url = pick(r, "srcUrl", "pbancUrl", "rcptUrl")
        edu = to_list(pick(r, "acbgCondNmLst", "acbgCondNm"))
        jobs.append({
            "id": "a" + str(sn),
            "src": "잡알리오",
            "org": str(pick(r, "instNm")).strip(),
            "title": str(pick(r, "recrutPbancTtl")).strip(),
            "start": ymd(pick(r, "pbancBgngYmd", "rcptBgngYmd")),
            "end": ymd(pick(r, "pbancEndYmd", "rcptEndYmd")),
            "region": to_list(pick(r, "workRgnNmLst", "workRgnNm")),
            "emp": simple_emp(to_list(pick(r, "hireTypeNmLst", "hireTypeNm"))),
            "career": str(pick(r, "recrutSeNm")).strip(),
            "eduFree": any("무관" in e for e in edu),
            "people": str(pick(r, "recrutNope")).strip(),
            "url": url if str(url).startswith("http") else "https://job.alio.go.kr",
        })
    return jobs, (sorted(records[0].keys()) if records else [])


# ---------- 2) 고용24 (공무직) ----------

def work24_query(key, extra):
    rows, page = [], 1
    while page <= 10:
        params = {"authKey": key, "callTp": "L", "returnType": "XML",
                  "startPage": page, "display": 100}
        params.update(extra)
        text = get(WORK24_URL, params)
        try:
            root = ET.fromstring(text.encode("utf-8"))
        except ET.ParseError:
            raise RuntimeError("고용24 응답을 읽을 수 없습니다(인증키 확인): " + text[:300])
        err = root.findtext(".//message") or root.findtext(".//error")
        items = root.findall(".//wanted")
        if not items and err:
            raise RuntimeError("고용24 오류: " + err)
        for it in items:
            rows.append({c.tag: (c.text or "").strip() for c in it})
        total = int(root.findtext(".//total") or 0)
        if not items or page * 100 >= total:
            break
        page += 1
    return rows


def fetch_work24(key):
    rows = []
    # 공공기관 + 무기계약(시간선택제 포함)
    rows += work24_query(key, {"coTp": "04", "empTp": "10|11"})
    # 기업형태와 상관없이 '공무직' 이 들어간 공고
    rows += work24_query(key, {"keyword": "공무직"})
    if rows:
        save_sample("sample_work24.json", rows[0])

    jobs = []
    for r in rows:
        title = pick(r, "title", "wantedTitle")
        url = pick(r, "wantedInfoUrl", "wantedMobileInfoUrl")
        career = str(pick(r, "career"))
        edu = str(pick(r, "minEdubg", "maxEdubg"))
        jobs.append({
            "id": "w" + str(pick(r, "wantedAuthNo")),
            "src": "고용24",
            "org": str(pick(r, "company", "busplaName")).strip(),
            "title": str(title).strip(),
            "start": ymd(pick(r, "regDt", "regDate")),
            "end": ymd(pick(r, "closeDt", "closeDate")),
            "region": region_of(pick(r, "region", "basicAddr")),
            "emp": ["공무직"],
            "career": "신입+경력" if ("관계없" in career or "무관" in career) else career,
            "eduFree": "무관" in edu,
            "people": "",
            "url": url if str(url).startswith("http") else "https://www.work24.go.kr",
        })
    return jobs, (sorted(rows[0].keys()) if rows else [])


# ---------- 공통 ----------

def clean(jobs, keys, label):
    good, seen = [], set()
    for j in jobs:
        if not j["org"] or not j["title"] or not j["end"] or j["end"] < TODAY:
            continue
        k = j["id"] if len(j["id"]) > 1 else j["org"] + j["title"]
        if k in seen:
            continue
        seen.add(k)
        good.append(j)
    if jobs and not good:
        print(f"[경고] {label}: 공고는 받았지만 칸 이름이 맞지 않습니다. 실제 칸: {', '.join(keys)}")
    return good


def main():
    os.makedirs(DOCS, exist_ok=True)
    alio_key = os.environ.get("JOB_API_KEY", "").strip()
    w24_key = os.environ.get("WORK24_API_KEY", "").strip()
    if not alio_key and not w24_key:
        sys.exit("인증키가 없습니다. GitHub Settings > Secrets 에 JOB_API_KEY / WORK24_API_KEY 를 등록하세요.")

    jobs, notes = [], []
    for label, key, fn in (("잡알리오", alio_key, fetch_alio), ("고용24", w24_key, fetch_work24)):
        if not key:
            notes.append(f"{label}: 인증키 없음, 건너뜀")
            continue
        try:
            got, keys = fn(key)
            ok = clean(got, keys, label)
            jobs += ok
            notes.append(f"{label}: {len(ok)}건 (원본 {len(got)}건)")
        except Exception as e:  # 한쪽이 실패해도 다른 쪽은 저장
            notes.append(f"{label}: 실패 - {e}")

    if not jobs:
        sys.exit("저장할 공고가 없습니다.\n" + "\n".join(notes))

    jobs.sort(key=lambda j: (j["end"], j["org"]))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
                   "count": len(jobs), "jobs": jobs}, f, ensure_ascii=False, separators=(",", ":"))
    print("저장 완료: 공고 " + str(len(jobs)) + "건\n" + "\n".join(notes))


if __name__ == "__main__":
    main()
