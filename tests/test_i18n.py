"""Every text passed to tr() must have a Portuguese translation.

Menus and messages kept showing up in English because new strings were added
without a matching entry in i18n._PT; this test lists any such string.
"""
from __future__ import annotations

import ast
from pathlib import Path

from mesadock.core import i18n

PACKAGE = Path(__file__).resolve().parent.parent / "mesadock"


def _tr_literals() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != "tr":
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.setdefault(arg.value, path.name + ":" + str(node.lineno))
    return found


def test_every_tr_string_has_a_portuguese_translation():
    missing = {text: where for text, where in _tr_literals().items() if text not in i18n._PT}
    assert not missing, "Sem tradução em i18n._PT:\n" + "\n".join(
        where + "  " + repr(text) for text, where in sorted(missing.items(), key=lambda kv: kv[1])
    )


def test_translations_keep_format_placeholders():
    for source, target in i18n._PT.items():
        for placeholder in ("{name}", "{count}", "{item}", "{dock}"):
            assert (placeholder in source) == (placeholder in target), (source, target)


def test_language_choice_is_a_saved_setting():
    from mesadock.core.models import Settings

    assert Settings().language == ""
    assert Settings(language="pt").language == "pt"
    assert Settings(language="xx").language == ""
