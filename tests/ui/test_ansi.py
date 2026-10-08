from anchorage.ui.widgets.ansi import Span, parse_ansi


def test_plain_text() -> None:
    assert parse_ansi("hello") == [Span("hello", None, False)]


def test_colours_and_reset() -> None:
    spans = parse_ansi("\x1b[31mred\x1b[0m plain \x1b[1;32mbold green\x1b[22m green")
    assert spans == [
        Span("red", 1, False),
        Span(" plain ", None, False),
        Span("bold green", 2, True),
        Span(" green", 2, False),
    ]


def test_bright_and_default() -> None:
    spans = parse_ansi("\x1b[92mok\x1b[39m back")
    assert spans == [Span("ok", 10, False), Span(" back", None, False)]


def test_non_sgr_sequences_are_stripped() -> None:
    assert parse_ansi("a\x1b[2Kb\x1b[1;1Hc\x1b]0;title\x07d") == [Span("abcd", None, False)]


def test_malformed_sequence_does_not_raise() -> None:
    assert parse_ansi("x\x1b[") == [Span("x", None, False)]
    assert parse_ansi("\x1b[999m y") == [Span(" y", None, False)]


def test_extended_colours_do_not_leak_arguments() -> None:
    assert parse_ansi("\x1b[38;5;1mx") == [Span("x", 1, False)]
    assert parse_ansi("\x1b[38;5;196mx") == [Span("x", None, False)]
    assert parse_ansi("\x1b[38;2;1;1;1mx") == [Span("x", None, False)]
    assert parse_ansi("\x1b[38;5;10mx") == [Span("x", 10, False)]
    assert parse_ansi("\x1b[31m\x1b[48;5;0mx") == [Span("x", 1, False)]
    assert parse_ansi("\x1b[48;2;1;2;3mx") == [Span("x", None, False)]


def test_colon_separated_and_other_csi_stripped() -> None:
    assert parse_ansi("\x1b[38:5:196mx") == [Span("x", None, False)]
    assert parse_ansi("a\x1b[3~b") == [Span("ab", None, False)]


def test_charset_designations_and_two_byte_escapes_are_stripped() -> None:
    assert parse_ansi("\x1b[1mbold\x1b(B\x1b[m") == [Span("bold", None, True)]
    assert parse_ansi("a\x1b)0b\x1b=c\x1b#8d") == [Span("abcd", None, False)]
