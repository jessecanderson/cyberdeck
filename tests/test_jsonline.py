import pytest

from cyberdeck.providers.jsonline import decode_message, encode_message


class ProtocolError(RuntimeError):
    pass


def test_jsonline_round_trip_is_compact_and_delimited() -> None:
    encoded = encode_message({"id": 1, "method": "initialize"})

    assert encoded == b'{"id":1,"method":"initialize"}\n'
    assert decode_message(encoded, protocol="TEST", error_type=ProtocolError) == {
        "id": 1,
        "method": "initialize",
    }


@pytest.mark.parametrize("line", [b"not-json\n", b"[]\n", b'"text"\n'])
def test_jsonline_rejects_malformed_or_non_object_frames(line: bytes) -> None:
    with pytest.raises(ProtocolError, match="Malformed TEST message|must be a JSON object"):
        decode_message(line, protocol="TEST", error_type=ProtocolError)
