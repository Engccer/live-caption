#!/usr/bin/env python3.12
"""probe.py 결과를 정답과 대조해 지연·화자분리·정확도를 채점한다(스파이크용)."""
import json
import re
import statistics as st
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
GT = json.loads((HERE / "ground_truth.json").read_text(encoding="utf-8"))


def norm(s):
    s = unicodedata.normalize("NFC", s or "")
    return re.sub(r"[^\w가-힣]", "", s)


def cer(ref, hyp):
    """문자 오류율 = 편집거리 / 정답 길이."""
    r, h = norm(ref), norm(hyp)
    if not r:
        return None
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i]
        for j, hc in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(r)


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def analyse(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    ev = d["events"]
    tr = [e for e in ev if e["kind"] == "transcript" and e.get("text")]

    # 화면에 글자가 뜨는 시점이 실제 발화보다 얼마나 뒤인가
    lag = [e["t_ms"] - e["audio_ms"] for e in tr
           if e.get("audio_ms") is not None]
    partial_lag = [e["t_ms"] - e["audio_ms"] for e in tr
                   if e.get("audio_ms") is not None and not e.get("final")]

    if d["provider"] == "muse":
        finals = [e for e in ev if e["kind"] == "speechComplete"]
        labels = [e["speaker"] for e in ev if e["kind"] == "speaker" and e.get("speaker")]
    else:
        finals = [e for e in tr if e.get("final")]
        labels = []
        for e in finals:
            labels += (e.get("speaker") or "").split(",") if e.get("speaker") else []
        labels = [x for x in labels if x]

    final_lag = [e["t_ms"] - e["audio_ms"] for e in finals
                 if e.get("audio_ms") is not None]
    hyp = " ".join(e.get("text") or "" for e in finals)
    ref = " ".join(t["text"] for t in GT["turns"])

    return {
        "provider": d["provider"],
        "audio_s": d["audio_ms"] / 1000,
        "events": len(ev),
        "partials": len(tr) - len([e for e in tr if e.get("final")]),
        "final_segments": len(finals),
        "gt_turns": len(GT["turns"]),
        "lag_median_ms": round(st.median(lag)) if lag else None,
        "lag_p90_ms": round(pct(lag, 90)) if lag else None,
        "partial_lag_median_ms": round(st.median(partial_lag)) if partial_lag else None,
        "final_lag_median_ms": round(st.median(final_lag)) if final_lag else None,
        "final_lag_max_ms": round(max(final_lag)) if final_lag else None,
        "distinct_speakers": len(set(labels)),
        "gt_speakers": len(GT["speakers"]),
        "speaker_labels": sorted(set(labels)),
        "cer": round(cer(ref, hyp), 4),
        "hyp": hyp.strip(),
    }


def main():
    rows = []
    for p in sorted(HERE.glob("result_*.json")):
        try:
            rows.append(analyse(p))
        except Exception as exc:
            print(f"{p.name} 채점 실패: {exc}")

    ref = " ".join(t["text"] for t in GT["turns"])
    out = ["# 실시간 STT 스파이크 실측 결과", "",
           f"- 음원: {GT['audio']} ({GT['total_ms'] / 1000:.1f}초, "
           f"{len(GT['turns'])}턴, 화자 {len(GT['speakers'])}명, 턴 간격 {GT['gap_ms']}ms)",
           f"- 조건: {GT['note']}", "",
           "## 지표", "",
           "| 지표 | " + " | ".join(r["provider"] for r in rows) + " |",
           "|---|" + "---|" * len(rows)]

    def row(label, key, unit=""):
        vals = []
        for r in rows:
            v = r.get(key)
            vals.append("측정 안 됨" if v is None else f"{v}{unit}")
        out.append(f"| {label} | " + " | ".join(vals) + " |")

    row("중간 결과(partial) 지연 중앙값", "partial_lag_median_ms", " ms")
    row("전체 이벤트 지연 중앙값", "lag_median_ms", " ms")
    row("전체 이벤트 지연 p90", "lag_p90_ms", " ms")
    row("확정 지연 중앙값", "final_lag_median_ms", " ms")
    row("확정 지연 최대", "final_lag_max_ms", " ms")
    row("partial 이벤트 수", "partials")
    row("확정 세그먼트 수 (정답 12턴)", "final_segments")
    row("구분된 화자 수 (정답 3명)", "distinct_speakers")
    row("문자오류율 CER", "cer")

    out += ["", "## 전사 결과 대조", "", "**정답**", "", f"> {ref}", ""]
    for r in rows:
        out += [f"**{r['provider']}** (화자 라벨: {r['speaker_labels']})", "",
                f"> {r['hyp']}", ""]

    (HERE / "findings.md").write_text("\n".join(out), encoding="utf-8")
    print("findings.md 작성 완료")


if __name__ == "__main__":
    main()
