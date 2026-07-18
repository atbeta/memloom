"""Tests for denoiser."""
import pytest
from memloom.pipeline.denoise import Denoiser


def test_unwrap_tool_output_json():
    d = Denoiser()
    content = '## user\n\nlist\n\n## tool\n\n{"output": "Host hz\\nHost rack\\nHost bwh", "exit_code": 0}\n\n## assistant\n\ndone'
    clean, changed = d.denoise(content)
    assert changed
    assert "Host hz" in clean
    assert "Host rack" in clean
    assert "Host bwh" in clean
    assert '"output"' not in clean
    assert '"exit_code"' not in clean
    assert "## user" in clean
    assert "## assistant" in clean


def test_unwrap_nested_tool_output():
    d = Denoiser()
    content = '# Header\n\n{"output": "line1\\nline2"}'
    clean, changed = d.denoise(content)
    assert changed
    assert "line1" in clean
    assert "line2" in clean
    assert "# Header" in clean


def test_no_change_on_clean_content():
    d = Denoiser()
    content = "## user\n\nhello world\n\n## assistant\n\nhi there"
    clean, changed = d.denoise(content)
    assert not changed
    assert clean == content


def test_denoise_record_preserves_metadata():
    from memloom.records import MemoryRecord
    d = Denoiser()
    rec = MemoryRecord(
        source="test",
        source_key="k1",
        content='## tool\n\n{"output": "Clean text", "exit_code": 0}\n\nDone',
        role="conversation_turn",
        agent="test",
    )
    new_rec, changed = d.denoise_record(rec)
    assert changed
    assert "Clean text" in new_rec.content
    assert new_rec.source == rec.source
    assert new_rec.source_key == rec.source_key
    assert new_rec.role == rec.role


def test_empty_content_unchanged():
    d = Denoiser()
    clean, changed = d.denoise("")
    assert not changed
    assert clean == ""


def test_multiple_tool_outputs():
    d = Denoiser()
    content = (
        '## tool\n\n{"output": "first"}\n\n'
        '## tool\n\n{"output": "second"}'
    )
    clean, changed = d.denoise(content)
    assert changed
    assert "first" in clean
    assert "second" in clean


def test_json_with_escaped_chars():
    d = Denoiser()
    content = '{"output": "line1\\nline2\\ttab"}'
    clean, changed = d.denoise(content)
    assert changed
    assert "line1\nline2\ttab" in clean


def test_non_output_json_kept():
    d = Denoiser()
    content = '{"type": "message", "role": "user"}'  # no output key
    clean, changed = d.denoise(content)
    assert not changed
    assert '"type"' in clean


def test_real_hermes_format():
    """Simulate actual Hermes conversation with tool output."""
    d = Denoiser()
    content = """## user

ca.pnb.pub

## assistant

checking

## tool

{"output": "Host ca bwh2 us2\\nHost hz 188.245.233.19", "exit_code": 0, "error": null}

## assistant

done"""
    clean, changed = d.denoise(content)
    assert changed
    assert "Host ca bwh2 us2" in clean
    assert "Host hz 188.245.233.19" in clean
    assert '"output"' not in clean
    assert '"exit_code"' not in clean
