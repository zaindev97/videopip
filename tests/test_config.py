import pytest
import yaml
from pydantic import ValidationError

from videopip import config, scaffold, tts


def test_templates_validate():
    for name in scaffold.TEMPLATES:
        config.Project.model_validate(yaml.safe_load(scaffold.template_text(name)))


def test_unknown_clip_reference_rejected():
    with pytest.raises(ValidationError, match="unknown clip id"):
        config.Project.model_validate({"clips": {"a": "a.mp4"},
                                       "segments": [{"title": "x", "clips": ["b"], "vo": "hi"}]})


def test_typo_field_rejected():
    with pytest.raises(ValidationError):
        config.Project.model_validate({"clips": {"a": "a.mp4"}, "segmnts": []})


def test_schema_exports():
    s = config.json_schema()
    assert "segments" in s["properties"]
    assert "base_dir" not in s["properties"]


def test_lexicon_whole_words_only():
    lex = {"Makita": "Mah-KEE-tah", "PEX": "pecks"}
    assert tts.apply_lexicon("Makita and PEX, not PEXA", lex) == "Mah-KEE-tah and pecks, not PEXA"


def test_sentence_alignment():
    text = "First one here. Second sentence now! Third?"
    words = [(0.0, .2, "First"), (.3, .2, "one"), (.6, .2, "here"), (1.2, .2, "Second"),
             (1.5, .2, "sentence"), (1.9, .2, "now"), (2.6, .2, "Third")]
    s = tts.sentences_from_words(text, words, 3.0)
    assert [x[0] for x in s] == [0.0, 1.2, 2.6]
