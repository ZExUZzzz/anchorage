from anchorage.core.terminal import SHELL_COMMAND, exec_command, find_terminal, open_shell


def which_from(*available: str):  # type: ignore[no-untyped-def]
    table = {name: f"/usr/bin/{name}" for name in available}

    def which(name: str) -> str | None:
        return table.get(name) or table.get(name.rsplit("/", 1)[-1])

    return which


def test_exec_command_uses_bash_with_sh_fallback() -> None:
    cmd = exec_command("abc123")
    assert cmd[:4] == ("docker", "exec", "-it", "abc123")
    assert cmd[4:] == ("sh", "-c", SHELL_COMMAND)
    assert "bash" in SHELL_COMMAND and "exec sh" in SHELL_COMMAND


def test_find_terminal_prefers_xdg_then_env_then_known() -> None:
    assert find_terminal({}, which_from("xdg-terminal-exec", "konsole")) == ("xdg-terminal-exec",)
    assert find_terminal({"TERMINAL": "kitty"}, which_from("kitty", "konsole")) == ("kitty",)
    assert find_terminal({"TERMINAL": "gnome-terminal"}, which_from("gnome-terminal")) == (
        "gnome-terminal",
        "--",
    )
    assert find_terminal({"TERMINAL": "/opt/bin/weird-term"}, which_from("weird-term")) == (
        "/opt/bin/weird-term",
        "-e",
    )
    assert find_terminal({"TERMINAL": "missing"}, which_from("alacritty", "xterm")) == (
        "alacritty",
        "-e",
    )
    assert find_terminal({}, which_from("xterm")) == ("xterm", "-e")
    assert find_terminal({}, which_from()) is None


def test_open_shell_launches_terminal() -> None:
    launched: list[list[str]] = []

    def launcher(argv: list[str]) -> bool:
        launched.append(argv)
        return True

    result = open_shell("abc", environ={}, which=which_from("docker", "konsole"), launcher=launcher)
    assert result.ok
    assert result.terminal == ("konsole", "-e")
    assert launched == [
        ["konsole", "-e", "/usr/bin/docker", "exec", "-it", "abc", "sh", "-c", SHELL_COMMAND]
    ]


def test_open_shell_without_docker_or_terminal() -> None:
    result = open_shell("abc", environ={}, which=which_from("konsole"), launcher=lambda argv: True)
    assert not result.ok
    assert result.reason is not None and "docker" in result.reason
    assert result.command[0] == "docker"

    result = open_shell("abc", environ={}, which=which_from("docker"), launcher=lambda argv: True)
    assert not result.ok
    assert result.terminal is None
    assert "terminal" in (result.reason or "")

    result = open_shell(
        "abc", environ={}, which=which_from("docker", "foot"), launcher=lambda argv: False
    )
    assert not result.ok
    assert result.terminal == ("foot",)


def test_open_shell_custom_command_is_split_with_quotes() -> None:
    launched: list[list[str]] = []
    launch = open_shell(
        "abc",
        command='"/opt/My Term/term" --single-instance -e',
        which=which_from("docker", "/opt/My Term/term", "konsole"),
        launcher=lambda argv: launched.append(argv) or True,
    )
    assert launch.ok
    assert launch.terminal == ("/opt/My Term/term", "--single-instance", "-e")
    assert launched == [
        ["/opt/My Term/term", "--single-instance", "-e", *exec_command("abc", "/usr/bin/docker")]
    ]


def test_open_shell_whitespace_command_keeps_auto_detection() -> None:
    launched: list[list[str]] = []
    launch = open_shell(
        "abc",
        command="   ",
        environ={},
        which=which_from("docker", "konsole"),
        launcher=lambda argv: launched.append(argv) or True,
    )
    assert launch.terminal == ("konsole", "-e")
    assert launched[0][0] == "konsole"


def test_open_shell_custom_command_with_unbalanced_quote_reports_reason() -> None:
    launch = open_shell(
        "abc", command='kitty "oops', which=which_from("docker"), launcher=lambda argv: True
    )
    assert not launch.ok
    assert launch.reason and "terminal command" in launch.reason


def test_open_shell_custom_command_not_found_reports_reason() -> None:
    launch = open_shell(
        "abc", command="nope -e", which=which_from("docker"), launcher=lambda argv: True
    )
    assert not launch.ok
    assert launch.reason and "nope" in launch.reason


def test_detected_terminal_joins_the_auto_command_or_is_empty() -> None:
    from anchorage.core.terminal import detected_terminal

    assert detected_terminal({}, which_from("konsole")) == "konsole -e"
    assert detected_terminal({}, which_from()) == ""


def test_open_shell_expands_home_in_the_executable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("HOME", "/home/u")
    launched: list[list[str]] = []
    seen: list[str] = []

    def which(name: str) -> str | None:
        seen.append(name)
        return name if name in ("/usr/bin/docker", "/home/u/bin/term", "docker") else None

    launch = open_shell(
        "abc", command="~/bin/term -e", which=which, launcher=lambda a: launched.append(a) or True
    )
    assert launch.ok
    assert launch.terminal == ("/home/u/bin/term", "-e")
    assert "/home/u/bin/term" in seen


def test_open_shell_quoted_empty_command_reports_reason() -> None:
    launch = open_shell("abc", command='""', which=which_from("docker"), launcher=lambda argv: True)
    assert not launch.ok
    assert launch.reason == "empty terminal command"
