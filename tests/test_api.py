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

    assert result == {"files": []}
    assert captured["repo_url"] == "https://github.com/example/repo"
    assert captured["ref"] == "main"
    assert captured["max_content_bytes"] == 1234
