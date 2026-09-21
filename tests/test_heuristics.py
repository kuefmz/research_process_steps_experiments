from research_process_steps.analyzer import analyze_file


def steps(path: str, content: str = "") -> set[str]:
    return set(analyze_file(path, content)["steps"])


def test_collection_file():
    assert "collection" in steps("scripts/download_dataset.py")


def test_processing_file():
    assert "processing" in steps("preprocessing/clean_records.py")


def test_source_code_is_implementation():
    assert "implementation" in steps("src/somef/cli.py")


def test_tests_are_implementation_not_evaluation():
    result = steps("tests/test_parser.py", "def test_parser(): pass")
    assert "implementation" in result
    assert "evaluation" not in result


def test_experiment_directory():
    assert "experimentation" in steps("experiments/create_models.py")


def test_scientific_evaluation():
    assert "evaluation" in steps("evaluation/benchmark.py", "f1_score = 0.91")


def test_documentation():
    assert "dissemination" in steps("docs/index.md")


def test_citation_file():
    assert "dissemination" in steps("CITATION.cff")


def test_generic_file_can_remain_unclassified():
    assert steps("assets/logo.png") == set()


def test_file_can_have_multiple_steps():
    result = steps(
        "experiments/evaluate_model.py",
        "random_seed = 42\nprint('f1_score')",
    )
    assert "experimentation" in result
    assert "evaluation" in result
