"""Startprüfungen der Anwendungskonfiguration."""

import pytest

from app import create_app
from app.config import Config


def _config(**overrides):
    return type("TestConfig", (Config,), {"SQLALCHEMY_DATABASE_URI": "sqlite://", **overrides})


def test_start_ohne_secret_key_schlaegt_fehl():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(_config(SECRET_KEY=None))


def test_start_mit_platzhalter_secret_key_schlaegt_fehl():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(_config(SECRET_KEY="change-me"))


def test_start_mit_altem_default_secret_key_schlaegt_fehl():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(_config(SECRET_KEY="dev-secret-key-change-me"))


def test_platzhalter_secret_key_im_testbetrieb_erlaubt():
    app = create_app(_config(SECRET_KEY="change-me", TESTING=True))
    assert app.config["SECRET_KEY"]


def test_echter_secret_key_wird_uebernommen():
    app = create_app(_config(SECRET_KEY="a" * 64))
    assert app.config["SECRET_KEY"] == "a" * 64
