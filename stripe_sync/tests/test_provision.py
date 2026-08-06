"""Создание пространства клиента: id из названия продукта, валидация."""

from stripe_sync.provision_util import (new_password, new_token, slugify_tenant,
                                        validate_signup)


def test_slug_from_product_name():
    assert slugify_tenant("Hub Content") == "hubcontent"
    assert slugify_tenant("VoiceForge.dev") == "voiceforgedev"
    assert slugify_tenant("PicSeat 2.0") == "picseat20"


def test_slug_transliterates_cyrillic():
    assert slugify_tenant("Мой Продукт") == "moiprodukt"


def test_slug_avoids_collisions_and_reserved():
    assert slugify_tenant("Hub Content", {"hubcontent"}) == "hubcontent2"
    assert slugify_tenant("Hub Content", {"hubcontent", "hubcontent2"}) == "hubcontent3"
    # служебные имена никогда не выдаются клиенту
    assert slugify_tenant("default") != "default"
    assert slugify_tenant("Retivo") != "retivo"


def test_slug_short_names_padded():
    out = slugify_tenant("Ok")
    assert len(out) >= 3 and out.isalnum()


def test_validate_signup():
    assert validate_signup("Hub Content", "owner@hub.com") == ""
    assert validate_signup("", "owner@hub.com") == "invalid_product_name"
    assert validate_signup("Hub", "not-an-email") == "invalid_email"
    assert validate_signup("Hub", "owner@hub") == "invalid_email"


def test_secrets_are_random_and_long():
    assert len({new_token() for _ in range(5)}) == 5
    assert len(new_token()) >= 24
    assert len(new_password()) == 16
    assert len({new_password() for _ in range(5)}) == 5
