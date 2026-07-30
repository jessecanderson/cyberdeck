from cyberdeck.command_runtime import HANDLERS_BY_KEY
from cyberdeck.commands import BUILTIN_COMMANDS, COMMANDS_BY_NAME, command_descriptions


def test_command_catalog_has_unique_canonical_names_and_aliases() -> None:
    names = [name for command in BUILTIN_COMMANDS for name in command.names]

    assert len(names) == len(set(names))
    assert set(COMMANDS_BY_NAME) == set(names)


def test_command_descriptions_only_expose_canonical_commands() -> None:
    descriptions = command_descriptions()

    assert list(descriptions) == [command.name for command in BUILTIN_COMMANDS]
    assert "/?" not in descriptions
    assert "/exit" not in descriptions
    assert COMMANDS_BY_NAME["/?"] is COMMANDS_BY_NAME["/help"]
    assert COMMANDS_BY_NAME["/exit"] is COMMANDS_BY_NAME["/quit"]


def test_command_catalog_owns_completion_spacing() -> None:
    assert COMMANDS_BY_NAME["/new"].append_space is True
    assert COMMANDS_BY_NAME["/density"].append_space is True
    assert COMMANDS_BY_NAME["/copy"].append_space is False


def test_every_builtin_command_resolves_to_a_handler() -> None:
    assert {command.handler_key for command in BUILTIN_COMMANDS} <= set(HANDLERS_BY_KEY)
