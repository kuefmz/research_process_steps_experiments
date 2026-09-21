from research_process_steps import api


def test_health_reports_no_ai():
    result = api.health()
    assert result["status"] == "ok"
    assert result["uses_ai"] is False


def test_analyze_endpoint_function_forwards_repository(monkeypatch):
    captured = {}

    def fake_analyze(repo_url, *, token=None, ref=None, max_content_bytes=None):
        captured.update(
            repo_url=repo_url,
            token=token,
            ref=ref,
            max_content_bytes=max_content_bytes,
        )
        return {"files": []}

    monkeypatch.setattr(api, "analyze_github_repository", fake_analyze)
    request = api.AnalyzeRequest(
        repo_url="https://github.com/example/repo",
        ref="main",
        max_content_bytes=1234,
    )

    result = api.analyze(request)

    assert result["files"] == []
    assert result["cache"]["hit"] is False
    assert result["cache"]["persistent"] is False
    assert captured["repo_url"] == "https://github.com/example/repo"
    assert captured["ref"] == "main"
    assert captured["max_content_bytes"] == 1234


def test_demo_cache_is_persistent(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "CACHE_DIR", tmp_path / "runtime")
    monkeypatch.setattr(api, "BUNDLED_CACHE_DIR", tmp_path / "bundled")
    calls = {"count": 0}

    def fake_analyze(repo_url, *, token=None, ref=None, max_content_bytes=None):
        calls["count"] += 1
        return {
            "repository": {"full_name": "dgarijo/Widoco", "ref": "master"},
            "files": [],
        }

    monkeypatch.setattr(api, "analyze_github_repository", fake_analyze)
    request = api.AnalyzeRequest(repo_url="https://github.com/dgarijo/Widoco")

    first = api.analyze(request)
    second = api.analyze(request)

    assert calls["count"] == 1
    assert first["cache"]["hit"] is False
    assert first["cache"]["persistent"] is True
    assert second["cache"]["hit"] is True
    assert second["cache"]["persistent"] is True
