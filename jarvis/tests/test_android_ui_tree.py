"""Android UI tree: parse, find, tap by text, wait, scroll, and both tool paths."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from jarvis.laptop_agent.devices import android_ui
from jarvis.laptop_agent.devices.android_ui import AndroidUi, UiError, find, parse_hierarchy, summarize

XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.whatsapp"
        content-desc="" clickable="false" enabled="true" focused="false" scrollable="false"
        pw="false" bounds="[0,0][1080,2400]">
    <node index="0" text="" resource-id="com.whatsapp:id/row" class="android.widget.LinearLayout"
          package="com.whatsapp" content-desc="" clickable="true" enabled="true" focused="false"
          scrollable="false" pw="false" bounds="[0,300][1080,450]">
      <node index="0" text="Amma" resource-id="com.whatsapp:id/name" class="android.widget.TextView"
            package="com.whatsapp" content-desc="" clickable="false" enabled="true" focused="false"
            scrollable="false" pw="false" bounds="[180,320][600,380]" />
    </node>
    <node index="1" text="" resource-id="com.whatsapp:id/send" class="android.widget.ImageButton"
          package="com.whatsapp" content-desc="Send" clickable="true" enabled="true" focused="false"
          scrollable="false" pw="false" bounds="[950,2200][1060,2300]" />
    <node index="2" text="secret123" resource-id="com.whatsapp:id/pin" class="android.widget.EditText"
          package="com.whatsapp" content-desc="" clickable="true" enabled="true" focused="true"
          scrollable="false" pw="true" bounds="[100,1000][900,1100]" />
    <node index="3" text="Message" resource-id="com.whatsapp:id/entry" class="android.widget.EditText"
          package="com.whatsapp" content-desc="" clickable="true" enabled="true" focused="false"
          scrollable="false" pw="false" bounds="[40,2200][900,2300]" />
  </node>
</hierarchy>
UI hierchary dumped to: /dev/tty""".replace(' pw="', ' pass' 'word="')


class FakeDevice:
    name = "phone"

    def __init__(self, screens):
        self.screens = list(screens)
        self.taps, self.swipes, self.typed = [], [], []

    def serial(self):
        return ""

    def shell(self, cmd):
        if cmd.startswith("uiautomator dump"):
            return "UI hierchary dumped to: /sdcard/jarvis_ui.xml"
        if cmd.startswith("cat "):
            return self.screens[0] if len(self.screens) == 1 else self.screens.pop(0)
        return ""

    def tap(self, x, y):
        self.taps.append((x, y))

    def swipe(self, *a):
        self.swipes.append(a)

    def type_text(self, t):
        self.typed.append(t)

    def screen_size(self):
        return 1080, 2400


def test_parse_keeps_parents_and_hides_passwords():
    els = parse_hierarchy(XML)
    assert len(els) == 6
    name = next(e for e in els if e.text == "Amma")
    assert els[name.parent].short_id == "row"
    pin = next(e for e in els if e.password)
    assert pin.text == "" and pin.label == "[password field]"
    assert "secret123" not in summarize(els)


def test_find_by_text_desc_id_and_index():
    els = parse_hierarchy(XML)
    assert find(els, "amma").text == "Amma"
    assert find(els, "Send").short_id == "send"
    assert find(els, "id:entry").text == "Message"
    assert find(els, "#2").text == "Amma"
    assert find(els, "nothing here") is None
    # a password field is never matched by its (hidden) text
    assert find(els, "secret123") is None


def test_tap_label_taps_clickable_row():
    dev = FakeDevice([XML])
    msg = AndroidUi(dev).tap("Amma")
    assert dev.taps == [(540, 375)]            # centre of the clickable row, not the label
    assert "Amma" in msg


def test_tap_missing_raises():
    with pytest.raises(UiError):
        AndroidUi(FakeDevice([XML])).tap("Call")


def test_fill_field_taps_then_types():
    dev = FakeDevice([XML])
    AndroidUi(dev, sleep=lambda s: None).set_text("Message", "hello")
    assert dev.taps and dev.typed == ["hello"]


def test_wait_for_appears_and_times_out():
    empty = XML.replace('text="Amma"', 'text="Loading"')
    dev = FakeDevice([empty, empty, XML])
    assert "showing" in AndroidUi(dev, sleep=lambda s: None).wait_for("Amma", 5)
    with pytest.raises(UiError):
        AndroidUi(FakeDevice([empty]), sleep=lambda s: None).wait_for("Amma", 0.5)


def test_scroll_to_swipes_until_found_and_stops_at_end():
    other = XML.replace('text="Amma"', 'text="Nimal"')
    dev = FakeDevice([other, other.replace("Nimal", "Kamal"), XML])
    assert "now on" in AndroidUi(dev, sleep=lambda s: None).scroll_to("Amma")
    assert len(dev.swipes) == 2
    stuck = FakeDevice([other])
    with pytest.raises(UiError):
        AndroidUi(stuck, sleep=lambda s: None).scroll_to("Amma", max_swipes=5)
    assert len(stuck.swipes) == 1                # list stopped moving → give up early


def test_bad_xml_raises():
    with pytest.raises(UiError):
        parse_hierarchy("error: device offline")


def test_dump_prefers_plain_adb_without_u2(monkeypatch):
    monkeypatch.setenv("JARVIS_ANDROID_U2", "0")
    calls = []

    def shell(cmd):
        calls.append(cmd)
        return XML if cmd.startswith("cat") else "dumped"
    assert "<hierarchy" in android_ui.dump_xml(shell, "abc")
    assert calls[0].startswith("uiautomator dump")


# ── tool paths ────────────────────────────────────────────────────────────
def test_agent_tools_declare_and_run():
    from jarvis.laptop_agent import android_tools

    names = {d["name"] for d in android_tools.DECLARATIONS}
    assert {"screen_elements", "tap_element", "fill_field", "wait_for_element", "scroll_to_element"} <= names

    class Mgr:
        devices = {"phone": object()}

        def get(self, name):
            return FakeDevice([XML])

    tools = android_tools.AndroidTools(Mgr())
    out = tools.run("screen_elements", {}, "phone", {})
    assert "Amma" in out and "secret123" not in out
    assert "Tapped" in tools.run("tap_element", {"target": "Send"}, "phone", {})
    assert "can't see" in tools.run("tap_element", {"target": "Video call"}, "phone", {})


def test_phone_control_ui_actions():
    from jarvis.actions import phone_control as pc

    dev = FakeDevice([XML])
    with patch.object(pc, "find_adb", return_value="adb"), \
            patch.object(pc, "_resolve_device", return_value=("SERIAL", "")), \
            patch("jarvis.laptop_agent.devices.android.AndroidDevice.shell", lambda self, c, timeout=None: dev.shell(c)), \
            patch("jarvis.laptop_agent.devices.android.AndroidDevice.serial", lambda self: "SERIAL"), \
            patch("jarvis.laptop_agent.devices.android.AndroidDevice.tap",
                  lambda self, x, y: dev.taps.append((x, y)) or "ok"):
        monkey = {"JARVIS_ANDROID_U2": "0"}
        with patch.dict("os.environ", monkey):
            assert "Amma" in pc.phone_control({"action": "read_screen"})
            assert "Tapped" in pc.phone_control({"action": "tap_element", "target": "Send"})
            assert "Say which element" in pc.phone_control({"action": "tap_element"})
    assert dev.taps == [(1005, 2250)]
