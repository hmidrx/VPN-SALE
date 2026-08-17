"""Telegram-native configurable purchase flow layered over support and delivery runtime."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import cast

from telegram_bot.application.identity import TelegramIdentityPort, now_utc
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import ConversationStateV2, ConversationStoreV2
from telegram_bot.formatting import format_toman
from telegram_bot.portal import CustomerPortalPort, PurchasePlan
from telegram_bot.purchase_api import (
    NativePurchaseChoice,
    NativePurchaseOptions,
    NativePurchasePortal,
    NativePurchaseRange,
)
from telegram_bot.runtime.handlers import (
    ButtonRows,
    HandlerResult,
    IncomingText,
    IncomingUser,
)
from telegram_bot.runtime.native_support_attachments import (
    NativeSupportAttachmentBotCommandHandler,
    NativeSupportAttachmentTelegramPollingRuntime,
)
from telegram_bot.screens import ScreenId
from telegram_bot.transport.polling import TelegramTransport

_PAGE_SIZE = 6


def _reviewed_plan(plan: PurchasePlan) -> str:
    return json.dumps(
        {
            "reference": plan.reference,
            "title": plan.title,
            "traffic_gb": plan.traffic_gb,
            "duration_days": plan.duration_days,
            "device_limit": plan.device_limit,
            "location_code": plan.location_code,
            "location_label": plan.location_label,
            "quality_code": plan.quality_code,
            "price_toman": plan.price_toman,
            "selection": plan.selection,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _partial(value: str | None) -> dict[str, int | str]:
    if not value:
        return {}
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("invalid purchase state")
    result: dict[str, int | str] = {}
    for key, item in decoded.items():
        if isinstance(key, str) and (
            (isinstance(item, int) and not isinstance(item, bool)) or isinstance(item, str)
        ):
            result[key] = item
    return result


def _token(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()[:10]


def _chunk(buttons: list[dict[str, str]], width: int = 2) -> ButtonRows:
    return [buttons[index : index + width] for index in range(0, len(buttons), width)]


class NativePurchaseBotCommandHandler(NativeSupportAttachmentBotCommandHandler):
    @property
    def native_purchase(self) -> NativePurchasePortal:
        return cast(NativePurchasePortal, self.portal)

    def _purchase_catalog(self, user: IncomingUser, locale: str) -> HandlerResult:
        items = self.native_purchase.native_purchase_catalog(self._portal_context(user, locale))
        if not items:
            return self._callback_message(
                "در حال حاضر پلن قابل خریدی وجود ندارد.", self.renderer.nav_rows(locale)
            )
        lines = ["🛒 خرید سرویس", "", "پلن موردنظر را انتخاب کنید:"]
        rows: ButtonRows = []
        for item in items[:10]:
            price = "قابل تنظیم" if item.price_toman is None else format_toman(item.price_toman)
            lines.append(f"• {item.title} — {price}")
            rows.append(
                [
                    {
                        "text": f"🛒 {item.title} — {price}",
                        "callback_data": BotCallback(
                            CallbackAction.SELECT_PLAN, item.reference
                        ).pack(),
                    }
                ]
            )
        rows.extend(self.renderer.nav_rows(locale))
        return self._callback_message("\n".join(lines), rows)

    def _render(
        self, user: IncomingUser, screen: object, locale: str, *, push: bool = True
    ) -> HandlerResult:
        if screen == ScreenId.BUY:
            key = self._conversation_key(user)
            state = self.conversations.get(key, now_utc()).move_to(ScreenId.BUY, push=push)
            self.conversations.save(key, state)
            return self._purchase_catalog(user, locale)
        return super()._render(user, screen, locale, push=push)

    def _save_config(
        self,
        user: IncomingUser,
        state: ConversationStateV2,
        plan_reference: str,
        selection: dict[str, int | str],
        expected_input: str,
    ) -> ConversationStateV2:
        updated = replace(
            state,
            conversation_kind="purchase_config",
            expected_input=expected_input,
            idempotency_key=None,
            selected_plan_reference=plan_reference,
            selected_options=json.dumps(
                selection, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ),
            active_order_reference=None,
        )
        self.conversations.save(self._conversation_key(user), updated)
        return updated

    @staticmethod
    def _range_text(title: str, option: NativePurchaseRange, unit: str) -> str:
        if option.minimum == option.maximum:
            return f"{title}: {option.minimum:,} {unit}"
        return (
            f"{title}\n\nبازه مجاز: {option.minimum:,} تا {option.maximum:,} {unit}\n"
            f"گام انتخاب: {option.step:,} {unit}"
        )

    def _range_rows(self, prefix: str, option: NativePurchaseRange) -> ButtonRows:
        buttons = [
            {
                "text": f"{value:,}",
                "callback_data": BotCallback(
                    CallbackAction.SELECT_PLAN, f"{prefix}.{value}"
                ).pack(),
            }
            for value in option.suggested
        ]
        rows = _chunk(buttons)
        rows.append(
            [
                {
                    "text": "✍️ مقدار دلخواه",
                    "callback_data": BotCallback(
                        CallbackAction.SELECT_PLAN, f"c{prefix}"
                    ).pack(),
                }
            ]
        )
        rows.append(
            [
                {
                    "text": "◀️ بازگشت به پلن‌ها",
                    "callback_data": BotCallback(CallbackAction.BUY_SERVICE).pack(),
                },
                {
                    "text": "❌ لغو خرید",
                    "callback_data": BotCallback(CallbackAction.CANCEL_CONVERSATION).pack(),
                },
            ]
        )
        return rows

    def _choice_rows(
        self,
        prefix: str,
        choices: tuple[NativePurchaseChoice, ...],
        page: int,
    ) -> ButtonRows:
        page = max(page, 0)
        start = page * _PAGE_SIZE
        current = choices[start : start + _PAGE_SIZE]
        buttons = [
            {
                "text": item.label,
                "callback_data": BotCallback(
                    CallbackAction.SELECT_PLAN, f"{prefix}.{_token(item.code)}"
                ).pack(),
            }
            for item in current
        ]
        rows = _chunk(buttons)
        pagination: list[dict[str, str]] = []
        if page > 0:
            pagination.append(
                {
                    "text": "◀️ قبلی",
                    "callback_data": BotCallback(
                        CallbackAction.SELECT_PLAN, f"{prefix}p.{page - 1}"
                    ).pack(),
                }
            )
        if start + _PAGE_SIZE < len(choices):
            pagination.append(
                {
                    "text": "بعدی ▶️",
                    "callback_data": BotCallback(
                        CallbackAction.SELECT_PLAN, f"{prefix}p.{page + 1}"
                    ).pack(),
                }
            )
        if pagination:
            rows.append(pagination)
        rows.append(
            [
                {
                    "text": "◀️ بازگشت به پلن‌ها",
                    "callback_data": BotCallback(CallbackAction.BUY_SERVICE).pack(),
                },
                {
                    "text": "❌ لغو خرید",
                    "callback_data": BotCallback(CallbackAction.CANCEL_CONVERSATION).pack(),
                },
            ]
        )
        return rows

    @staticmethod
    def _resolve_choice(
        choices: tuple[NativePurchaseChoice, ...], token: str
    ) -> NativePurchaseChoice | None:
        matches = [item for item in choices if _token(item.code) == token]
        return matches[0] if len(matches) == 1 else None

    def _begin_review(
        self,
        user: IncomingUser,
        locale: str,
        state: ConversationStateV2,
        plan: PurchasePlan,
        update_id: int,
    ) -> HandlerResult:
        balance = self.portal.wallet_balance(self._portal_context(user, locale))[0]
        reviewed = _reviewed_plan(plan)
        purchase_state = state.start_purchase(plan.reference, reviewed, f"tg-buy:{update_id}")
        self.conversations.save(self._conversation_key(user), purchase_state)
        details = (
            f"🛒 بررسی سفارش\n\nپلن: {plan.title}\nموقعیت: {plan.location_label}\n"
            f"حجم: {plan.traffic_gb:,} گیگابایت\nمدت: {plan.duration_days} روز\n"
            f"تعداد دستگاه: {plan.device_limit}\nقیمت: {format_toman(plan.price_toman)}\n"
            f"موجودی کیف پول: {format_toman(balance)}"
        )
        if balance < plan.price_toman:
            return self._callback_message(
                details + f"\n\nمبلغ کسری: {format_toman(plan.price_toman - balance)}",
                [
                    [
                        {
                            "text": "➕ افزایش موجودی",
                            "callback_data": BotCallback(CallbackAction.TOP_UP).pack(),
                        }
                    ],
                    [
                        {
                            "text": "✏️ تغییر انتخاب",
                            "callback_data": BotCallback(
                                CallbackAction.SELECT_PLAN, plan.reference
                            ).pack(),
                        }
                    ],
                    [
                        {
                            "text": "◀️ بازگشت به پلن‌ها",
                            "callback_data": BotCallback(CallbackAction.BUY_SERVICE).pack(),
                        }
                    ],
                ],
            )
        return self._callback_message(
            details,
            [
                [
                    {
                        "text": "✅ تأیید و خرید",
                        "callback_data": BotCallback(CallbackAction.CONFIRM_PURCHASE).pack(),
                    }
                ],
                [
                    {
                        "text": "✏️ تغییر انتخاب",
                        "callback_data": BotCallback(
                            CallbackAction.SELECT_PLAN, plan.reference
                        ).pack(),
                    },
                    {
                        "text": "◀️ بازگشت به پلن‌ها",
                        "callback_data": BotCallback(CallbackAction.BUY_SERVICE).pack(),
                    },
                ],
                [
                    {
                        "text": "❌ لغو خرید",
                        "callback_data": BotCallback(CallbackAction.CANCEL_CONVERSATION).pack(),
                    }
                ],
            ],
        )

    def _advance(
        self,
        user: IncomingUser,
        locale: str,
        state: ConversationStateV2,
        options: NativePurchaseOptions,
        selection: dict[str, int | str],
        update_id: int,
    ) -> HandlerResult:
        if "traffic_gb" not in selection:
            if options.traffic_gb.minimum == options.traffic_gb.maximum:
                selection["traffic_gb"] = options.traffic_gb.minimum
            else:
                self._save_config(user, state, options.reference, selection, "purchase_traffic")
                return self._callback_message(
                    self._range_text("📦 حجم سرویس", options.traffic_gb, "گیگابایت"),
                    self._range_rows("t", options.traffic_gb),
                )
        if "duration_days" not in selection:
            if options.duration_days.minimum == options.duration_days.maximum:
                selection["duration_days"] = options.duration_days.minimum
            else:
                self._save_config(user, state, options.reference, selection, "purchase_duration")
                return self._callback_message(
                    self._range_text("⏳ مدت سرویس", options.duration_days, "روز"),
                    self._range_rows("d", options.duration_days),
                )
        if "device_count" not in selection:
            if options.devices.minimum == options.devices.maximum:
                selection["device_count"] = options.devices.minimum
            else:
                self._save_config(user, state, options.reference, selection, "purchase_devices")
                return self._callback_message(
                    self._range_text("📱 تعداد دستگاه", options.devices, "دستگاه"),
                    self._range_rows("n", options.devices),
                )
        if "location_code" not in selection:
            if len(options.locations) == 1:
                selection["location_code"] = options.locations[0].code
            else:
                self._save_config(user, state, options.reference, selection, "purchase_location")
                return self._callback_message(
                    "🌍 موقعیت سرویس را انتخاب کنید.",
                    self._choice_rows("l", options.locations, 0),
                )
        if "quality_code" not in selection:
            if len(options.qualities) == 1:
                selection["quality_code"] = options.qualities[0].code
            else:
                self._save_config(user, state, options.reference, selection, "purchase_quality")
                return self._callback_message(
                    "⚡ کیفیت سرویس را انتخاب کنید.",
                    self._choice_rows("q", options.qualities, 0),
                )
        plan = self.native_purchase.native_purchase_preview(
            self._portal_context(user, locale), options.reference, selection
        )
        return self._begin_review(user, locale, state, plan, update_id)

    def _select_plan(
        self, user: IncomingUser, locale: str, reference: str, update_id: int
    ) -> HandlerResult:
        options = self.native_purchase.native_purchase_options(
            self._portal_context(user, locale), reference
        )
        if options is None:
            return self._stale(locale)
        state = self.conversations.get(self._conversation_key(user), now_utc())
        state = self._save_config(user, state, reference, {}, "purchase_config")
        return self._advance(user, locale, state, options, {}, update_id)

    def _option_callback(
        self,
        user: IncomingUser,
        locale: str,
        value: str,
        update_id: int,
    ) -> HandlerResult:
        key = self._conversation_key(user)
        state = self.conversations.get(key, now_utc())
        if (
            state.conversation_kind != "purchase_config"
            or not state.selected_plan_reference
            or state.selected_options is None
        ):
            return self._stale(locale)
        options = self.native_purchase.native_purchase_options(
            self._portal_context(user, locale), state.selected_plan_reference
        )
        if options is None:
            return self._stale(locale)
        try:
            selection = _partial(state.selected_options)
        except (ValueError, json.JSONDecodeError):
            return self._stale(locale)

        if value in {"ct", "cd", "cn"}:
            field = {"ct": "traffic", "cd": "duration", "cn": "devices"}[value]
            option = {
                "traffic": options.traffic_gb,
                "duration": options.duration_days,
                "devices": options.devices,
            }[field]
            unit = {"traffic": "گیگابایت", "duration": "روز", "devices": "دستگاه"}[field]
            expected = f"purchase_{field}_text"
            self._save_config(user, state, options.reference, selection, expected)
            return self._callback_message(
                f"مقدار را به عدد ارسال کنید.\n"
                f"بازه: {option.minimum:,} تا {option.maximum:,} {unit} — گام: {option.step:,}",
                [
                    [
                        {
                            "text": "❌ لغو خرید",
                            "callback_data": BotCallback(
                                CallbackAction.CANCEL_CONVERSATION
                            ).pack(),
                        }
                    ]
                ],
            )

        if value.startswith(("lp.", "qp.")):
            prefix, _, raw_page = value.partition(".")
            try:
                page = int(raw_page)
            except ValueError:
                return self._stale(locale)
            if prefix == "lp":
                return self._callback_message(
                    "🌍 موقعیت سرویس را انتخاب کنید.",
                    self._choice_rows("l", options.locations, page),
                )
            return self._callback_message(
                "⚡ کیفیت سرویس را انتخاب کنید.",
                self._choice_rows("q", options.qualities, page),
            )

        prefix, separator, raw = value.partition(".")
        if not separator:
            return self._stale(locale)
        if prefix in {"t", "d", "n"}:
            try:
                numeric = int(raw)
            except ValueError:
                return self._stale(locale)
            option = {
                "t": options.traffic_gb,
                "d": options.duration_days,
                "n": options.devices,
            }[prefix]
            field = {"t": "traffic_gb", "d": "duration_days", "n": "device_count"}[prefix]
            if not option.accepts(numeric):
                return self._stale(locale)
            selection[field] = numeric
        elif prefix in {"l", "q"}:
            choices = options.locations if prefix == "l" else options.qualities
            choice = self._resolve_choice(choices, raw)
            if choice is None:
                return self._stale(locale)
            selection["location_code" if prefix == "l" else "quality_code"] = choice.code
        else:
            return self._stale(locale)
        return self._advance(user, locale, state, options, selection, update_id)

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback, update_id: int
    ) -> HandlerResult:
        if callback.action == CallbackAction.SELECT_PLAN:
            if callback.value.startswith("p_"):
                return self._select_plan(user, locale, callback.value, update_id)
            return self._option_callback(user, locale, callback.value, update_id)
        return super()._route_callback(user, locale, callback, update_id)

    def handle_text(self, message: IncomingText) -> HandlerResult:
        if message.chat_type != "private" or message.user is None:
            return super().handle_text(message)
        key = self._conversation_key(message.user)
        state = self.conversations.get(key, now_utc())
        expected = state.expected_input or ""
        if state.conversation_kind != "purchase_config" or expected not in {
            "purchase_traffic_text",
            "purchase_duration_text",
            "purchase_devices_text",
        }:
            return super().handle_text(message)
        if not self.idempotency.claim(
            message.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            return HandlerResult(True, True, ())
        if not state.selected_plan_reference or state.selected_options is None:
            return self._stale("fa")
        options = self.native_purchase.native_purchase_options(
            self._portal_context(message.user, "fa"), state.selected_plan_reference
        )
        if options is None:
            return self._stale("fa")
        cleaned = message.text.strip().replace(",", "").replace("٬", "").replace("،", "")
        try:
            numeric = int(cleaned)
            selection = _partial(state.selected_options)
        except (ValueError, json.JSONDecodeError):
            return self._callback_message("فقط یک عدد معتبر ارسال کنید.", [])
        option = {
            "purchase_traffic_text": options.traffic_gb,
            "purchase_duration_text": options.duration_days,
            "purchase_devices_text": options.devices,
        }[expected]
        field = {
            "purchase_traffic_text": "traffic_gb",
            "purchase_duration_text": "duration_days",
            "purchase_devices_text": "device_count",
        }[expected]
        if not option.accepts(numeric):
            return self._callback_message(
                f"این مقدار مجاز نیست. بازه {option.minimum:,} تا {option.maximum:,} "
                f"با گام {option.step:,} است.",
                [],
            )
        selection[field] = numeric
        return self._advance(message.user, "fa", state, options, selection, message.update_id)


class NativePurchaseTelegramPollingRuntime(NativeSupportAttachmentTelegramPollingRuntime):
    def __init__(
        self,
        settings: BotSettings,
        identity: TelegramIdentityPort,
        transport: TelegramTransport | None = None,
        *,
        portal: CustomerPortalPort | None = None,
        conversations: ConversationStoreV2 | None = None,
        retry_base_seconds: float = 0.2,
        retry_max_seconds: float = 5.0,
    ) -> None:
        super().__init__(
            settings,
            identity,
            transport,
            portal=portal,
            conversations=conversations,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
        )
        self.handler = NativePurchaseBotCommandHandler(
            settings,
            identity,
            portal=portal,
            conversations=conversations,
        )
