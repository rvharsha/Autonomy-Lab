"""Parse temporary credential files as data, without invoking a shell."""

import pytest

from autonomy_lab.credentials import KEY_NAMES, gemini_key


@pytest.fixture(autouse=True)
def empty_model_credentials(monkeypatch):
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("name", ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY"])
def test_allowed_environment_key_precedes_file_contents(tmp_path, monkeypatch, name):
    path = tmp_path / ".env"
    path.write_text('GEMINI_API_KEY="invalid-quote\nUNRELATED_SECRET=unit-unrelated-secret\n')
    monkeypatch.setenv(name, "unit-environment-key")
    assert gemini_key(path) == "unit-environment-key"


def test_environment_key_preference_is_explicit(tmp_path, monkeypatch):
    for name in KEY_NAMES:
        monkeypatch.setenv(name, f"unit-{name}")
    assert gemini_key(tmp_path / "missing.env") == "unit-GEMINI_API_KEY"
    monkeypatch.delenv("GEMINI_API_KEY")
    assert gemini_key(tmp_path / "missing.env") == "unit-GOOGLE_API_KEY"
    monkeypatch.delenv("GOOGLE_API_KEY")
    assert gemini_key(tmp_path / "missing.env") == "unit-GEMINI_KEY"


@pytest.mark.parametrize("entry", [
    "GEMINI_API_KEY=unit-file-key", "GOOGLE_API_KEY='unit-file-key'",
    'GEMINI_KEY="unit-file-key"', 'export GEMINI_API_KEY = "unit-file-key" # comment',
])
def test_only_relevant_keys_are_parsed_and_quotes_are_supported(tmp_path, entry):
    path = tmp_path / ".env"
    path.write_text('UNRELATED_SECRET="intentionally-invalid-quote\nOTHER=unit-other-secret\n' + entry + "\n")
    assert gemini_key(path) == "unit-file-key"


@pytest.mark.parametrize("expression", [
    "$(touch {marker})", "`touch {marker}`", "${HOME}/model-key", "$GEMINI_API_KEY",
])
def test_shell_expressions_remain_literal_and_never_execute(tmp_path, expression):
    marker = tmp_path / "must-not-exist"
    literal = expression.format(marker=marker) if "{marker}" in expression else expression
    path = tmp_path / ".env"
    path.write_text(f"GEMINI_API_KEY='{literal}'\n")
    assert gemini_key(path) == literal
    assert not marker.exists()


def test_unrelated_shell_commands_are_ignored_not_executed(tmp_path):
    marker = tmp_path / "must-not-exist"
    path = tmp_path / ".env"
    path.write_text(f"touch {marker}\nexport OTHER=$(touch {marker})\nGEMINI_API_KEY=unit-key\n")
    assert gemini_key(path) == "unit-key"
    assert not marker.exists()


def test_empty_environment_value_allows_selected_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    path = tmp_path / ".env"
    path.write_text("GEMINI_API_KEY=unit-file-key\n")
    assert gemini_key(path) == "unit-file-key"


@pytest.mark.parametrize("contents", [None, "UNRELATED_SECRET=unit-unrelated-secret\n", "GEMINI_API_KEY=''\n"])
def test_missing_key_error_is_helpful_and_does_not_expose_file_secrets(tmp_path, contents):
    path = tmp_path / ".env"
    if contents is not None:
        path.write_text(contents)
    with pytest.raises(RuntimeError, match="No Gemini credential found.*environment.*selected .env") as raised:
        gemini_key(path)
    assert "unit-unrelated-secret" not in str(raised.value)


def test_bad_relevant_quoting_is_reported_without_echoing_key(tmp_path):
    path = tmp_path / ".env"
    path.write_text('GEMINI_API_KEY="unit-private-test-key\n')
    with pytest.raises(ValueError, match="invalid quoting") as raised:
        gemini_key(path)
    assert "unit-private-test-key" not in str(raised.value)
