from pipeline.stages import stage1_script


def test_local_fallback_produces_beats():
    result = stage1_script.run("Test topic")
    assert result["topic"] == "Test topic"
    assert result["source"] in ("gemini", "groq", "openrouter", "local_template")
    assert len(result["beats"]) > 0
    for beat in result["beats"]:
        assert isinstance(beat["text"], str) and beat["text"]
        assert beat["seconds"] > 0


def test_empty_topic_raises():
    try:
        stage1_script.run("")
        assert False, "expected Stage1Error"
    except stage1_script.Stage1Error:
        pass
