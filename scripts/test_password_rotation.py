"""Quick checks for TMS password rotation suffix replacement."""

from utils.tms import TmsUser


def test_with_rotation_number_keeps_length() -> None:
    cases = [
        ("Abcdef@9", 10, "Abcdef10"),
        ("Abc@ef99", 100, "Abc@e100"),
        ("Abcdef10", 11, "Abcdef11"),
        ("Abc@e100", 101, "Abc@e101"),
    ]
    for old_password, rotation_number, expected in cases:
        result = TmsUser.with_rotation_number(old_password, rotation_number)
        assert result == expected, f"{old_password} -> {rotation_number}: got {result!r}, want {expected!r}"
        assert len(result) == len(old_password), f"length changed for {old_password!r}"


def test_next_rotation_candidate() -> None:
    assert TmsUser.with_rotation_number("Abcdef@9", 10) == "Abcdef10"
    assert TmsUser.with_rotation_number("Abc@ef99", 100) == "Abc@e100"


if __name__ == "__main__":
    test_with_rotation_number_keeps_length()
    test_next_rotation_candidate()
    print("password rotation tests passed")
