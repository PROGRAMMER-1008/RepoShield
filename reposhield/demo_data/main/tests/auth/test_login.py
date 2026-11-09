from auth.login import check_password, hash_password


def test_password_check():
    h = hash_password("hunter2", "salt")
    assert check_password("hunter2", "salt", h)
    assert not check_password("wrong", "salt", h)
