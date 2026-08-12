"""Pure-logic tests for the subtitle/text exporters (no native deps)."""

from voicetype import transcribe
from voicetype.transcribe import TranscriptResult, to_srt, to_txt, to_vtt

SEGMENTS = [
    {"start": 0.0, "end": 1.5, "text": "hello world"},
    {"start": 2.0, "end": 3.25, "text": "second line"},
]


def test_to_txt_exact():
    assert to_txt(SEGMENTS) == "hello world\nsecond line"


def test_to_txt_skips_blank_segments():
    segs = [{"start": 0, "end": 1, "text": "  "}, {"start": 1, "end": 2, "text": "hi"}]
    assert to_txt(segs) == "hi"


def test_to_srt_exact():
    expected = (
        "1\n00:00:00,000 --> 00:00:01,500\nhello world\n"
        "\n"
        "2\n00:00:02,000 --> 00:00:03,250\nsecond line\n"
    )
    assert to_srt(SEGMENTS) == expected


def test_to_vtt_exact():
    expected = (
        "WEBVTT\n"
        "\n"
        "00:00:00.000 --> 00:00:01.500\nhello world\n"
        "\n"
        "00:00:02.000 --> 00:00:03.250\nsecond line\n"
    )
    assert to_vtt(SEGMENTS) == expected


def test_timestamp_formatting_hours():
    # 3661.5s -> 01:01:01,500
    assert transcribe._fmt_ts(3661.5) == "01:01:01,500"
    assert transcribe._fmt_ts(3661.5, ".") == "01:01:01.500"


def test_srt_fallback_timings_when_missing():
    segs = [{"start": None, "end": None, "text": "no timing"}]
    out = to_srt(segs)
    # start falls back to 0, end to start + 2.0
    assert out == "1\n00:00:00,000 --> 00:00:02,000\nno timing\n"


def test_exporters_accept_transcript_result():
    result = TranscriptResult("hello world\nsecond line", SEGMENTS)
    assert to_txt(result) == "hello world\nsecond line"
    assert to_srt(result).startswith("1\n00:00:00,000")
    assert result.to_dict()["segments"][0]["text"] == "hello world"
