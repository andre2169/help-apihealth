import pytest

from app.schemas.validators import validate_password


def test_overlong_password_uses_a_clear_user_facing_message():
    with pytest.raises(ValueError) as error:
        validate_password("á" * 37 + "A1")

    assert str(error.value) == "A senha ficou muito longa. Tente uma senha menor."
    assert "bytes" not in str(error.value).lower()
