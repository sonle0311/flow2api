"""Capacity snapshot exposes limits as numbers only, never account data."""

from types import SimpleNamespace

from src.core.integration_reference import build_capacity


def settings(method="personal", **overrides):
    values = dict(captcha_method=method, browser_count=2, personal_max_resident_tabs=5,
                  flow_image_launch_soft_limit=20, flow_video_launch_soft_limit=20,
                  flow_image_launch_stagger_ms=400, flow_video_launch_stagger_ms=400,
                  flow_image_slot_wait_timeout=480.0, flow_video_slot_wait_timeout=480.0)
    values.update(overrides)
    return SimpleNamespace(**values)


def token(active=True, image=3, video=2, **extra):
    return SimpleNamespace(is_active=active, image_enabled=True, video_enabled=True,
                           image_concurrency=image, video_concurrency=video,
                           email="secret@example.com", st="SECRET-ST", at="SECRET-AT", **extra)


def test_recommendation_is_the_tightest_limit():
    capacity = build_capacity(settings(), [token(), token(), token(), token(active=False, image=50)])
    assert capacity["captcha_parallel_slots"] == 10
    assert capacity["captcha_third_party"] is False
    assert capacity["image"]["accounts_total_concurrency"] == 9
    assert capacity["image"]["recommended_max_parallel_requests"] == 9
    assert capacity["video"]["recommended_max_parallel_requests"] == 6
    assert capacity["image"]["active_accounts"] == 3
    assert "secret" not in repr(capacity).lower()


def test_unlimited_accounts_fall_back_to_captcha_and_launch_limits():
    capacity = build_capacity(settings(browser_count=1, personal_max_resident_tabs=4), [token(image=-1)])
    assert capacity["image"]["accounts_total_concurrency"] is None
    assert capacity["image"]["per_account_concurrency"] == [-1]
    assert capacity["image"]["recommended_max_parallel_requests"] == 4


def test_third_party_solver_and_no_accounts():
    capacity = build_capacity(settings("yescaptcha", flow_image_launch_soft_limit=0), [])
    assert capacity["captcha_third_party"] is True
    assert capacity["captcha_parallel_slots"] is None
    assert capacity["image"]["launch_soft_limit"] is None
    assert capacity["image"]["recommended_max_parallel_requests"] == 0


def test_personal_slots_are_capped_at_fifty():
    capacity = build_capacity(settings(browser_count=20, personal_max_resident_tabs=50), [token(image=-1)])
    assert capacity["captcha_parallel_slots"] == 50
