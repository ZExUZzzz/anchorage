"""Read Qt ``.ts`` translation catalogues for the tests."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from anchorage.ui import i18n

LANGUAGE_CODES = ("ru", "de", "es", "fr", "zh_CN")
# The .ts sources live in the source tree only (the wheel ships the compiled .qm), so read them
# from the checkout; the .qm files are checked where the installed package keeps them.
CATALOGUE_DIR = Path(__file__).resolve().parents[1] / "src" / "anchorage" / "i18n"
INSTALLED_CATALOGUE_DIR = Path(i18n.CATALOGUE_DIR)


@dataclass(frozen=True, slots=True)
class Message:
    context: str
    source: str
    comment: str
    numerus: bool
    translations: tuple[str, ...]
    unfinished: bool

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.context, self.source, self.comment)

    @property
    def translated(self) -> bool:
        return not self.unfinished and all(text.strip() for text in self.translations)


@dataclass(frozen=True, slots=True)
class Catalogue:
    language: str
    messages: tuple[Message, ...]

    def keys(self) -> set[tuple[str, str, str]]:
        return {message.key for message in self.messages}


def ts_path(language: str) -> Path:
    return CATALOGUE_DIR / f"anchorage_{language}.ts"


def parse_ts(path: Path) -> Catalogue:
    root = ET.parse(path).getroot()
    messages: list[Message] = []
    for context in root.iter("context"):
        name = context.findtext("name") or ""
        for message in context.iter("message"):
            translation = message.find("translation")
            assert translation is not None, f"{path.name}: {name}: message without translation"
            forms = [form.text or "" for form in translation.iter("numerusform")]
            if not forms:
                forms = [translation.text or ""]
            messages.append(
                Message(
                    context=name,
                    source=message.findtext("source") or "",
                    comment=message.findtext("comment") or "",
                    numerus=message.get("numerus") == "yes",
                    translations=tuple(forms),
                    unfinished=translation.get("type") in ("unfinished", "vanished", "obsolete"),
                )
            )
    return Catalogue(root.get("language") or "", tuple(messages))


def load_catalogue(language: str) -> Catalogue:
    return parse_ts(ts_path(language))
