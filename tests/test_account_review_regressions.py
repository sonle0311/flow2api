"""Account review regressions use only synthetic providers and temporary SQLite."""

import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.api import admin
from src.core.account_tiers import supports_model_for_tier
from src.core.database import Database
from src.core.models import Token
from src.services.token_manager import TokenManager


class AccountReviewRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Database(self.directory.name + "/flow.db")
        await self.db.init_db()
        self.flow = MagicMock()
        self.flow.FRONTEND_ACCESS_TOKEN = "flow-frontend-cookie"
        self.flow.get_request_fingerprint.return_value = None
        self.flow.get_updated_flow_cookies.side_effect = lambda original: original
        self.flow.st_to_at = AsyncMock(return_value={
            "access_token": self.flow.FRONTEND_ACCESS_TOKEN,
            "expires": (datetime.now(timezone.utc) + timedelta(minutes=55)).isoformat(),
            "credits": 0,
            "userPaygateTier": None,
        })
        self.flow.get_credits = AsyncMock(return_value={"credits": 0, "userPaygateTier": None})
        self.manager = TokenManager(self.db, self.flow)
        self.token_id = await self.db.add_token(Token(
            st="frontend-synthetic", at=self.flow.FRONTEND_ACCESS_TOKEN,
            at_expires=datetime.now(timezone.utc) - timedelta(hours=11),
            email="synthetic@example.com", login_account="synthetic@example.com",
            google_cookies="OSID=synthetic; SID=synthetic",
            user_paygate_tier="PAYGATE_TIER_TWO",
        ))

    async def asyncTearDown(self):
        self.directory.cleanup()

    async def ban_eligible(self):
        await self.db.update_token(
            self.token_id, is_active=False, ban_reason="429_rate_limit",
            banned_at=datetime.now(timezone.utc) - timedelta(hours=13),
        )

    async def test_admin_metadata_edit_preserves_disabled_state_and_ban_metadata(self):
        for reason in (None, "429_rate_limit"):
            with self.subTest(reason=reason):
                banned_at = datetime.now(timezone.utc) - timedelta(hours=2) if reason else None
                await self.db.update_token(
                    self.token_id, is_active=False, ban_reason=reason, banned_at=banned_at,
                    at_expires=datetime.now(timezone.utc) + timedelta(minutes=50),
                )
                with patch.multiple(admin, token_manager=self.manager, concurrency_manager=None):
                    result = await admin.update_token(
                        self.token_id, admin.UpdateTokenRequest(remark="metadata only"), "admin",
                    )
                self.assertTrue(result["success"])
                saved = await self.db.get_token(self.token_id)
                self.assertFalse(saved.is_active)
                self.assertEqual(saved.ban_reason, reason)
                self.assertEqual(saved.banned_at, banned_at)
                self.assertEqual(saved.remark, "metadata only")

    async def test_admin_replacement_credentials_reactivate_explicitly(self):
        await self.ban_eligible()
        with patch.multiple(admin, token_manager=self.manager, concurrency_manager=None):
            await admin.update_token(
                self.token_id, admin.UpdateTokenRequest(google_cookies="OSID=replacement; SID=synthetic"), "admin",
            )
        saved = await self.db.get_token(self.token_id)
        self.assertTrue(saved.is_active)
        self.assertIsNone(saved.ban_reason)

    async def test_capsolver_connectivity_fallback_does_not_report_a_score(self):
        captcha = SimpleNamespace(captcha_method="capsolver", browser_proxy_enabled=False, browser_proxy_url="")
        fake_db = SimpleNamespace(get_captcha_config=AsyncMock(return_value=captcha))
        with patch.object(admin, "db", fake_db), patch.object(
            admin, "_solve_recaptcha_with_api_service", new=AsyncMock(return_value="synthetic-captcha"),
        ):
            result = await admin.test_captcha_score(
                admin.CaptchaScoreTestRequest(website_url="https://antcpt.com/score_detector/"), "admin",
            )
        self.assertTrue(result["token_acquired"])
        self.assertIsNone(result["score"])
        self.assertIsNone(result["verify_http_status"])
        self.assertFalse(result["verified"])
        self.assertTrue(result["connectivity_only"])

    async def test_verified_solver_diagnostic_retains_the_actual_score(self):
        captcha = SimpleNamespace(captcha_method="capsolver", browser_proxy_enabled=False, browser_proxy_url="")
        fake_db = SimpleNamespace(get_captcha_config=AsyncMock(return_value=captcha))
        response = MagicMock(status_code=200)
        response.json.return_value = {"success": True, "score": 0.37}
        session = MagicMock()
        session.__aenter__.return_value = session
        session.post = AsyncMock(return_value=response)
        with patch.object(admin, "db", fake_db), patch.object(
            admin, "_solve_recaptcha_with_api_service", new=AsyncMock(return_value="synthetic-captcha"),
        ), patch.object(admin, "AsyncSession", return_value=session), patch.object(
            admin, "_resolve_score_test_verify_proxy", new=AsyncMock(return_value=(None, False, "none", "")),
        ):
            result = await admin.test_captcha_score(
                admin.CaptchaScoreTestRequest(website_url="https://synthetic.example/diagnostic"), "admin",
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["score"], 0.37)
        self.assertEqual(result["verify_http_status"], 200)
        session.post.assert_awaited_once()

    async def test_refresh_waiter_cancellation_does_not_cancel_shared_work(self):
        for cancelled_index in (0, 1):
            with self.subTest(cancelled_index=cancelled_index):
                started, release = asyncio.Event(), asyncio.Event()

                async def refresh(_token_id):
                    started.set()
                    await release.wait()
                    return True

                with patch.object(self.manager, "_refresh_at_inner", side_effect=refresh) as refresh_call:
                    creator = asyncio.create_task(self.manager._refresh_at(self.token_id))
                    await started.wait()
                    reuse = asyncio.create_task(self.manager._refresh_at(self.token_id))
                    await asyncio.sleep(0)
                    waiters = [creator, reuse]
                    waiters[cancelled_index].cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await waiters[cancelled_index]
                    release.set()
                    try:
                        self.assertTrue(await waiters[1 - cancelled_index])
                    except asyncio.CancelledError:
                        self.fail("Cancelling one waiter cancelled another request's shared refresh")
                    refresh_call.assert_called_once()
                self.assertNotIn(self.token_id, self.manager._refresh_futures)

    async def test_account_deletion_still_cancels_the_shared_refresh(self):
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def refresh(_token_id):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        with patch.object(self.manager, "_refresh_at_inner", side_effect=refresh):
            waiter = asyncio.create_task(self.manager._refresh_at(self.token_id))
            await started.wait()
            await self.manager.delete_token(self.token_id)
            with self.assertRaises(asyncio.CancelledError):
                await waiter
        self.assertTrue(cancelled.is_set())
        self.assertIsNone(await self.db.get_token(self.token_id))

    async def test_repeated_and_concurrent_usage_increments_existing_count(self):
        await self.db.update_token(self.token_id, use_count=7)
        await self.manager.record_usage(self.token_id)
        await self.manager.record_usage(self.token_id, is_video=True)
        other = TokenManager(Database(self.db.db_path), self.flow)
        await asyncio.gather(*(
            (self.manager if index % 2 else other).record_usage(self.token_id, is_video=bool(index % 2))
            for index in range(24)
        ))
        saved = await self.db.get_token(self.token_id)
        stats = await self.db.get_token_stats(self.token_id)
        self.assertEqual(saved.use_count, 33)
        self.assertIsNotNone(saved.last_used_at)
        self.assertEqual(stats.image_count, 13)
        self.assertEqual(stats.video_count, 13)

    async def test_frontend_429_recovery_validates_cookies_despite_synthetic_expiry(self):
        await self.ban_eligible()
        await self.manager.auto_unban_429_tokens()
        saved = await self.db.get_token(self.token_id)
        self.assertTrue(saved.is_active)
        self.assertIsNone(saved.ban_reason)
        self.flow.st_to_at.assert_awaited_once()
        self.assertGreater(saved.at_expires, datetime.now(timezone.utc))

    async def test_invalid_frontend_session_remains_banned_after_cooldown(self):
        await self.ban_eligible()
        self.flow.st_to_at.side_effect = RuntimeError("401 UNAUTHENTICATED")
        await self.manager.auto_unban_429_tokens()
        saved = await self.db.get_token(self.token_id)
        self.assertFalse(saved.is_active)
        self.assertEqual(saved.ban_reason, "429_rate_limit")
        self.flow.st_to_at.assert_awaited_once()

    async def test_frontend_recovery_respects_manual_disable_and_new_cookie_push(self):
        for change in ("manual_disable", "cookie_push", "new_ban"):
            with self.subTest(change=change):
                await self.ban_eligible()

                async def validate(*_args, **_kwargs):
                    if change == "manual_disable":
                        await self.manager.disable_token(self.token_id)
                    elif change == "cookie_push":
                        await self.db.update_token(self.token_id, google_cookies="OSID=new; SID=synthetic")
                    else:
                        await self.manager.ban_token_for_429(self.token_id)
                    return {"access_token": self.flow.FRONTEND_ACCESS_TOKEN, "credits": 0}

                self.flow.st_to_at.reset_mock()
                self.flow.st_to_at.side_effect = validate
                await self.manager.auto_unban_429_tokens()
                self.assertFalse((await self.db.get_token(self.token_id)).is_active)
                self.flow.st_to_at.assert_awaited()

    async def test_manual_disable_prevents_later_automatic_429_reactivation(self):
        await self.ban_eligible()
        await self.db.update_token(self.token_id, at_expires=datetime.now(timezone.utc) + timedelta(hours=1))
        await self.manager.disable_token(self.token_id)
        await self.manager.auto_unban_429_tokens()
        self.assertFalse((await self.db.get_token(self.token_id)).is_active)
        self.flow.st_to_at.assert_not_awaited()

    async def test_frontend_cooldown_and_legacy_real_expiry_are_still_respected(self):
        await self.ban_eligible()
        await self.db.update_token(self.token_id, banned_at=datetime.now(timezone.utc) - timedelta(hours=1))
        await self.manager.auto_unban_429_tokens()
        self.assertFalse((await self.db.get_token(self.token_id)).is_active)
        self.flow.st_to_at.assert_not_awaited()
        await self.ban_eligible()
        await self.db.update_token(self.token_id, at="legacy-expiring-token")
        await self.manager.auto_unban_429_tokens()
        self.assertFalse((await self.db.get_token(self.token_id)).is_active)
        self.flow.st_to_at.assert_not_awaited()

    async def test_balance_only_validation_and_credit_refresh_preserve_verified_tier(self):
        for path in ("validation", "credits", "legacy_refresh", "rotated_refresh", "managed_save"):
            with self.subTest(path=path):
                for returned_tier in (None, "UNRECOGNIZED"):
                    await self.db.update_token(
                        self.token_id, user_paygate_tier="PAYGATE_TIER_TWO", credits=100,
                        last_st_refresh_at=datetime.now(timezone.utc), at=self.flow.FRONTEND_ACCESS_TOKEN,
                    )
                    self.manager._clear_at_validation_cache(self.token_id)
                    self.flow.get_credits.return_value = {"credits": 0, "userPaygateTier": returned_tier}
                    self.flow.st_to_at.return_value = {
                        "access_token": self.flow.FRONTEND_ACCESS_TOKEN,
                        "credits": 0, "userPaygateTier": returned_tier,
                    }
                    token = await self.db.get_token(self.token_id)
                    if path == "validation":
                        await self.manager.ensure_valid_token(token)
                    elif path == "credits":
                        self.manager._mark_at_valid(self.token_id)
                        await self.manager.refresh_credits(self.token_id)
                    elif path == "managed_save":
                        await self.manager.save_managed_browser_cookies(
                            self.token_id, {"email": token.email, "google_cookies": token.google_cookies},
                        )
                    else:
                        if path == "rotated_refresh":
                            self.flow.st_to_at.return_value["google_cookies"] = "OSID=rotated; SID=synthetic"
                        self.assertTrue(await self.manager._do_refresh_at(self.token_id, token.st, token))
                    saved = await self.db.get_token(self.token_id)
                    self.assertEqual(saved.credits, 0)
                    self.assertEqual(saved.user_paygate_tier, "PAYGATE_TIER_TWO")

    async def test_explicit_verified_tier_change_is_persisted(self):
        self.flow.get_credits.return_value = {"credits": 0, "userPaygateTier": "PAYGATE_TIER_ONE"}
        self.manager._mark_at_valid(self.token_id)
        await self.db.update_token(self.token_id, last_st_refresh_at=datetime.now(timezone.utc))
        await self.manager.refresh_credits(self.token_id)
        self.assertEqual((await self.db.get_token(self.token_id)).user_paygate_tier, "PAYGATE_TIER_ONE")

    async def test_cookie_identity_change_cannot_inherit_previous_account_entitlement(self):
        for returned_tier in (None, "UNRECOGNIZED", "PAYGATE_TIER_ONE"):
            with self.subTest(returned_tier=returned_tier):
                await self.db.update_token(
                    self.token_id, email="synthetic@example.com", login_account="synthetic@example.com",
                    user_paygate_tier="PAYGATE_TIER_TWO",
                )
                self.flow.st_to_at.return_value["userPaygateTier"] = returned_tier
                snapshot = await self.db.get_token(self.token_id)
                await self.manager._save_refreshed_cookies(self.token_id, snapshot, {
                    "email": "replacement@example.com", "google_cookies": "OSID=replacement; SID=replacement",
                })
                saved = await self.db.get_token(self.token_id)
                self.assertEqual(saved.email, "replacement@example.com")
                self.assertEqual(saved.login_account, "replacement@example.com")
                self.assertEqual(
                    saved.user_paygate_tier,
                    "PAYGATE_TIER_ONE" if returned_tier == "PAYGATE_TIER_ONE" else None,
                )

    async def test_explicit_identity_replacement_clears_previous_account_entitlement(self):
        for replacement in (
            {"email": "replacement@example.com", "login_account": "replacement@example.com"},
            {"email": "replacement@example.com"},
            {"login_account": "replacement@example.com"},
        ):
            with self.subTest(replacement=replacement):
                await self.db.update_token(
                    self.token_id, email="synthetic@example.com", login_account="synthetic@example.com",
                    user_paygate_tier="PAYGATE_TIER_TWO",
                )
                await self.manager.update_token(self.token_id, **replacement)
                self.assertIsNone((await self.db.get_token(self.token_id)).user_paygate_tier)

    async def test_same_identity_edits_preserve_previous_verified_entitlement(self):
        await self.db.update_token(self.token_id, login_account="")
        await self.manager.update_token(
            self.token_id, email="SYNTHETIC@EXAMPLE.COM", login_account="synthetic@example.com", remark="same identity",
        )
        self.assertEqual((await self.db.get_token(self.token_id)).user_paygate_tier, "PAYGATE_TIER_TWO")

    async def test_generic_cookie_replacement_cannot_inherit_claimed_account_tier(self):
        for claimed_email in (None, "synthetic@example.com"):
            with self.subTest(claimed_email=claimed_email):
                await self.db.update_token(
                    self.token_id, google_cookies="OSID=original; SID=synthetic", user_paygate_tier="PAYGATE_TIER_TWO",
                )
                await self.manager.update_token(
                    self.token_id, google_cookies="OSID=replacement; SID=synthetic", login_account=claimed_email,
                )
                saved = await self.db.get_token(self.token_id)
                self.assertIsNone(saved.user_paygate_tier)
                self.assertFalse(supports_model_for_tier("gemini-3.5-flash-image-4k", saved.user_paygate_tier))

    async def test_validated_entrypoints_replace_cookie_entitlement_from_upstream_only(self):
        await self.db.update_plugin_config("synthetic-plugin", auto_enable_on_update=False)
        for entrypoint in ("admin", "plugin", "import"):
            for returned_tier in (None, "PAYGATE_TIER_ONE"):
                with self.subTest(entrypoint=entrypoint, returned_tier=returned_tier):
                    await self.db.update_token(
                        self.token_id, google_cookies="OSID=original; SID=synthetic", user_paygate_tier="PAYGATE_TIER_TWO",
                    )
                    self.flow.st_to_at.return_value["userPaygateTier"] = returned_tier
                    payload = {"google_cookies": "OSID=replacement; SID=synthetic", "login_account": "synthetic@example.com"}
                    with patch.multiple(admin, db=self.db, token_manager=self.manager, concurrency_manager=None):
                        if entrypoint == "admin":
                            response = await admin.update_token(self.token_id, admin.UpdateTokenRequest(**payload), "admin")
                            self.assertTrue(response["success"])
                        elif entrypoint == "plugin":
                            response = await admin.plugin_update_token(
                                admin.PluginTokenUpdateRequest(**payload), "Bearer synthetic-plugin",
                            )
                            self.assertEqual(response["action"], "updated")
                        else:
                            response = await admin.import_tokens(
                                admin.ImportTokensRequest(tokens=[admin.ImportTokenItem(**payload)]), "admin",
                            )
                            self.assertEqual(response["updated"], 1)
                            self.assertFalse(response["errors"])
                    saved = await self.db.get_token(self.token_id)
                    self.assertEqual(saved.user_paygate_tier, returned_tier)
                    self.assertFalse(supports_model_for_tier("gemini-3.5-flash-image-4k", saved.user_paygate_tier))

    async def test_unchanged_cookie_and_observed_same_identity_rotation_preserve_tier(self):
        original = await self.db.get_token(self.token_id)
        await self.manager.update_token(self.token_id, google_cookies=original.google_cookies, remark="same cookie")
        self.assertEqual((await self.db.get_token(self.token_id)).user_paygate_tier, "PAYGATE_TIER_TWO")
        await self.manager._save_refreshed_cookies(self.token_id, original, {
            "email": original.email, "google_cookies": "OSID=rotated; SID=synthetic",
        })
        self.assertEqual((await self.db.get_token(self.token_id)).user_paygate_tier, "PAYGATE_TIER_TWO")

    async def test_new_unknown_account_import_does_not_acquire_paid_entitlement(self):
        self.flow.create_project = AsyncMock(return_value="synthetic-project")
        self.manager._get_project_pool_size = lambda: 1
        for index, state in enumerate(("missing", "unknown", "error")):
            with self.subTest(state=state):
                self.flow.create_project.return_value = f"synthetic-project-{index}"
                self.flow.st_to_at.return_value["user"] = {"email": f"new-synthetic-{index}@example.com"}
                self.flow.get_credits.return_value = {
                    "credits": 100,
                    **({"userPaygateTier": "UNRECOGNIZED"} if state == "unknown" else {}),
                }
                self.flow.get_credits.side_effect = RuntimeError("Synthetic credits unavailable") if state == "error" else None
                token = await self.manager.add_token(f"synthetic-new-session-{index}")
                self.assertIsNone(token.user_paygate_tier)
                saved = await self.db.get_token(token.id)
                self.assertIsNone(saved.user_paygate_tier)
                self.assertFalse(supports_model_for_tier("gemini-3.5-flash-image-2k", saved.user_paygate_tier))
                self.assertFalse(supports_model_for_tier("gemini-3.5-flash-image-4k", saved.user_paygate_tier))
