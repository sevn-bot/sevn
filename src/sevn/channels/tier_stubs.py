"""Tier 1-3 stub channel entry-point classes.

Module: sevn.channels.tier_stubs
Depends: sevn.channels.stub

Exports:
    SignalChannelAdapter — Tier 1 stub.
    WhatsappChannelAdapter — Tier 1 stub.
    MatrixChannelAdapter — Tier 2 stub.
    TeamsChannelAdapter — Tier 2 stub.
    EmailChannelAdapter — Tier 2 stub.
    SmsChannelAdapter — Tier 2 stub.
    DingtalkChannelAdapter — Tier 3 stub.
    FeishuChannelAdapter — Tier 3 stub.
    WecomChannelAdapter — Tier 3 stub.
    WeixinChannelAdapter — Tier 3 stub.
    QqChannelAdapter — Tier 3 stub.
    YuanbaoChannelAdapter — Tier 3 stub.
    LineChannelAdapter — Tier 3 stub.
    NtfyChannelAdapter — Tier 3 stub.
    BluebubblesChannelAdapter — Tier 3 stub.
    GoogleChatChannelAdapter — Tier 3 stub.
    MattermostChannelAdapter — Tier 3 stub.
    HomeassistantChannelAdapter — Tier 3 stub.
"""

from __future__ import annotations

from sevn.channels.stub import make_stub_adapter_class

SignalChannelAdapter = make_stub_adapter_class("signal", label="Signal")
WhatsappChannelAdapter = make_stub_adapter_class("whatsapp", label="WhatsApp")
MatrixChannelAdapter = make_stub_adapter_class("matrix", label="Matrix")
TeamsChannelAdapter = make_stub_adapter_class("teams", label="Microsoft Teams")
EmailChannelAdapter = make_stub_adapter_class("email", label="Email")
SmsChannelAdapter = make_stub_adapter_class("sms", label="SMS")
DingtalkChannelAdapter = make_stub_adapter_class("dingtalk", label="DingTalk")
FeishuChannelAdapter = make_stub_adapter_class("feishu", label="Feishu")
WecomChannelAdapter = make_stub_adapter_class("wecom", label="WeCom")
WeixinChannelAdapter = make_stub_adapter_class("weixin", label="Weixin")
QqChannelAdapter = make_stub_adapter_class("qq", label="QQ")
YuanbaoChannelAdapter = make_stub_adapter_class("yuanbao", label="Yuanbao")
LineChannelAdapter = make_stub_adapter_class("line", label="LINE")
NtfyChannelAdapter = make_stub_adapter_class("ntfy", label="ntfy")
BluebubblesChannelAdapter = make_stub_adapter_class("bluebubbles", label="BlueBubbles")
GoogleChatChannelAdapter = make_stub_adapter_class("google_chat", label="Google Chat")
MattermostChannelAdapter = make_stub_adapter_class("mattermost", label="Mattermost")
HomeassistantChannelAdapter = make_stub_adapter_class("homeassistant", label="Home Assistant")
