"""기술 용어는 영어로, 문장은 해요체로 (사용자 요청 2026-10-26).
export_web.py 가 해설 본문·버킷 이름에 적용하고, web/ 소스에도 같은 표를 한 번 적용했다.
긴 표현부터 바꾼다."""
import re

TERMS = [
    (r"지운 블록 반납\(discard\)은", "Discard는"),
    (r"지운 블록은", "Discard는"),
    (r"블록 반납\(discard\)", "Discard"),
    (r"블록 반납", "Discard"),
    (r"Discard은", "Discard는"),
    (r"Discard을", "Discard를"),
    (r"Discard이 ", "Discard가 "),
    (r"저장장치 위치 접근 지도", "LBA heatmap"),
    (r"저장장치 위치\(LBA\)", "LBA"),
    (r"저장장치 위치", "LBA"),
    (r"쓰기 경로", "Write path"),
    (r"쓰기 비중", "Write ratio"),
    (r"응답 시간\(dtoc\)", "Latency(dtoc)"),
    (r"응답 시간", "Latency"),
    (r"요청 사이 간격", "Inter-arrival"),
    (r"요청 간격", "Inter-arrival"),
    (r"요청 크기", "Request size"),
    (r"동시 요청 수", "QD"),
    (r"동시 요청", "QD"),
    (r"큐 깊이", "queue depth"),
    (r"이어진 요청", "Sequential"),
    (r"순차 비율", "sequential ratio"),
    (r"쉬는 시간", "Idle"),
    (r"가장 긴 쉼", "Max gap"),
    (r"깨어남", "Wakeups"),
    (r"최고 속도", "Peak throughput"),
    (r"끊긴 프레임", "Jank frame"),
    (r"화면 끊김\(jank\)", "Jank"),
    (r"메타데이터", "Metadata"),
    (r"요청 수", "Requests"),
    (r"워크로드 시그니처", "Workload signature"),
    (r"워크로드 지도", "Workload map"),
    (r"느린 요청", "Slow requests"),
    (r"측정 구간", "trace window"),
    (r"측정 시간", "Duration"),
    (r"시간축", "Timeline"),
    (r"총량", "Volume"),
    (r"중앙값", "median"),
    (r"(\d)·(\d)회차", r"Run \1·\2"),
    (r"첫 회차", "Run 1"),
    (r"(\d)회차", r"Run \1"),
    (r"회차", "Run"),
    (r"스텝", "Step"),
    (r"프로세스", "Process"),
    (r"스레드", "Thread"),
    (r"파일 종류", "File type"),
    (r"읽기", "Read"),
    (r"쓰기", "Write"),
    (r"지연", "Latency"),
    (r"저장장치\(UFS\)", "UFS"),
    (r"저장장치", "UFS"),
]

# 데이터 쪽 버킷·분류 이름
FLOW = ["App (buffered)", "Kernel writeback", "fsync", "Metadata/node", "GC", "Other"]
KIND = {"DB": "DB", "WAL·journal": "WAL/journal", "APK·so·odex": "APK/so/odex", "사진·영상": "Photo/Video",
        "캐시": "Cache", "이름 없음": "(no name)", "기타": "Other"}

_RX = [(re.compile(a), b) for a, b in TERMS]


def en(s: str) -> str:
    for rx, b in _RX:
        s = rx.sub(b, s)
    return s
