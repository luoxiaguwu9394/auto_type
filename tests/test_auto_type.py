"""auto_type 的测试。

只测两个 seam：`load_payload`（编码检测）和 `build_plan`（语料 → 笔画序列）。
两者都是纯边界，不需要真的敲键盘。测试名用 GLOSSARY.md 的术语：语料、笔画、回退、节奏。
"""

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auto_type


def apply_strokes(strokes):
    """把笔画序列还原成语料——模拟目标输入框最终会剩什么。"""
    out = []
    for stroke in strokes:
        if stroke.kind == "char":
            out.append(stroke.text)
        elif stroke.kind == "backspace":
            if out:
                out.pop()
        elif stroke.kind == "enter":
            out.append("\n")
    return "".join(out)


class TestBuildPlanReproducesPayload(unittest.TestCase):
    def test_plan_reproduces_chinese_payload_exactly(self):
        config = auto_type.Config(
            humanize=True, retract_probability=1.0, retract_max=3, delay_min=1, delay_max=2
        )
        payload = "这是一段中文，还有 English 和标点。"
        strokes = auto_type.build_plan(payload, config, rng=random.Random(7))
        self.assertEqual(apply_strokes(strokes), payload)

    def test_plan_reproduces_payload_with_newlines(self):
        config = auto_type.Config(
            humanize=True, retract_probability=0.5, retract_max=2, delay_min=1, delay_max=2
        )
        payload = "第一行\n第二行\n\n第四行"
        strokes = auto_type.build_plan(payload, config, rng=random.Random(11))
        self.assertEqual(apply_strokes(strokes), payload)

    def test_crlf_is_normalised_to_lf(self):
        config = auto_type.Config(humanize=False, delay_min=1, delay_max=1)
        strokes = auto_type.build_plan("a\r\nb", config, rng=random.Random(0))
        self.assertEqual(apply_strokes(strokes), "a\nb")


class TestNewlineHandling(unittest.TestCase):
    def test_newline_becomes_enter_by_default(self):
        config = auto_type.Config(humanize=False, send_enter=True, delay_min=1, delay_max=1)
        strokes = auto_type.build_plan("a\nb", config, rng=random.Random(0))
        self.assertEqual([s.kind for s in strokes], ["char", "enter", "char"])

    def test_newline_becomes_space_when_enter_disabled(self):
        config = auto_type.Config(humanize=False, send_enter=False, delay_min=1, delay_max=1)
        strokes = auto_type.build_plan("a\nb", config, rng=random.Random(0))
        self.assertEqual(apply_strokes(strokes), "a b")


class TestRetraction(unittest.TestCase):
    def test_retraction_backspaces_then_retypes(self):
        config = auto_type.Config(
            humanize=True, retract_probability=1.0, retract_max=2, delay_min=1, delay_max=1
        )
        strokes = auto_type.build_plan("abcdef", config, rng=random.Random(3))
        self.assertTrue(any(s.kind == "backspace" for s in strokes))
        # 回退之后内容依然正确——错误被修正回去了
        self.assertEqual(apply_strokes(strokes), "abcdef")

    def test_no_retraction_when_humanize_off(self):
        config = auto_type.Config(
            humanize=False, retract_probability=1.0, retract_max=3, delay_min=1, delay_max=1
        )
        strokes = auto_type.build_plan("abcdef", config, rng=random.Random(3))
        self.assertFalse(any(s.kind == "backspace" for s in strokes))


class TestSupplementaryBarrier(unittest.TestCase):
    """增补字符是回退屏障：目标端未必能整字退格，跨越它退格会让认知错位。"""

    def _config(self):
        return auto_type.Config(
            humanize=True, retract_probability=1.0, retract_max=3, delay_min=1, delay_max=1
        )

    def test_retraction_never_crosses_a_supplementary_character(self):
        strokes = auto_type.build_plan("a\U0001f600b", self._config(), rng=random.Random(0))
        self.assertEqual(
            [(s.kind, s.text) for s in strokes],
            [
                ("char", "a"), ("backspace", "\b"), ("char", "a"),
                ("char", "\U0001f600"),  # 屏障：不回退、也不被划进删除范围
                ("char", "b"), ("backspace", "\b"), ("char", "b"),
            ],
        )

    def test_a_lone_supplementary_character_is_never_retracted(self):
        strokes = auto_type.build_plan("\U00020bb7", self._config(), rng=random.Random(0))
        self.assertEqual([(s.kind, s.text) for s in strokes], [("char", "\U00020bb7")])

    def test_retraction_resumes_after_the_barrier(self):
        payload = "\U0001f600abcd"
        strokes = auto_type.build_plan(payload, self._config(), rng=random.Random(0))
        self.assertTrue(any(s.kind == "backspace" for s in strokes))
        self.assertEqual(apply_strokes(strokes), payload)
        # 屏障之后 recent 是空的，第一次回退只能删 1 个字，不能倒退到 emoji 之前
        first_backspace_run = 0
        for stroke in strokes:
            if stroke.kind == "backspace":
                first_backspace_run += 1
            elif first_backspace_run:
                break
        self.assertLessEqual(first_backspace_run, 1)

    def test_barrier_survives_a_real_payload(self):
        """真实语料 + 多种子：最终内容必须始终等于语料。"""
        payload = "第一行 中文\n第二行 😀🎉 与 𠮷 混排 abc"
        expected = payload.replace("\r\n", "\n").replace("\r", "\n")
        config = auto_type.Config(
            humanize=True, retract_probability=0.05, retract_max=3, delay_min=1, delay_max=2
        )
        for seed in range(100):
            strokes = auto_type.build_plan(payload, config, rng=random.Random(seed))
            self.assertEqual(apply_strokes(strokes), expected, f"seed={seed}")


class TestCadence(unittest.TestCase):
    def test_waits_fall_in_configured_range_when_jitter_off(self):
        config = auto_type.Config(humanize=False, delay_min=10, delay_max=20)
        strokes = auto_type.build_plan("abcdefgh", config, rng=random.Random(5))
        for stroke in strokes:
            self.assertGreaterEqual(stroke.wait_ms, 10)
            self.assertLessEqual(stroke.wait_ms, 20)

    def test_enter_is_preceded_by_line_pause_when_humanized(self):
        config = auto_type.Config(
            humanize=True,
            delay_min=5,
            delay_max=10,
            jitter=0.0,
            line_pause_min=300,
            line_pause_max=300,
            retract_probability=0.0,
        )
        strokes = auto_type.build_plan("a\nb", config, rng=random.Random(0))
        enter = next(s for s in strokes if s.kind == "enter")
        self.assertEqual(enter.wait_ms, 300)

    def test_no_line_pause_when_humanize_off(self):
        config = auto_type.Config(
            humanize=False,
            delay_min=5,
            delay_max=5,
            line_pause_min=300,
            line_pause_max=300,
        )
        strokes = auto_type.build_plan("a\nb", config, rng=random.Random(0))
        enter = next(s for s in strokes if s.kind == "enter")
        self.assertEqual(enter.wait_ms, 5)


class TestUtf16Units(unittest.TestCase):
    def test_bmp_character_is_one_unit(self):
        self.assertEqual(auto_type.utf16_units("中"), [0x4E2D])
        self.assertEqual(auto_type.utf16_units("a"), [0x61])

    def test_supplementary_character_is_two_units(self):
        units = auto_type.utf16_units("\U0001f600")
        self.assertEqual(len(units), 2)
        self.assertEqual(units[0], 0xD83D)
        self.assertEqual(units[1], 0xDE00)

    def test_surrogate_pair_survives_a_round_trip(self):
        config = auto_type.Config(humanize=False, delay_min=1, delay_max=1)
        payload = "笑\U0001f600了"
        strokes = auto_type.build_plan(payload, config, rng=random.Random(0))
        self.assertEqual(apply_strokes(strokes), payload)


class TestLoadPayload(unittest.TestCase):
    def test_reads_utf8_with_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text("中文内容", encoding="utf-8-sig")
            self.assertEqual(auto_type.load_payload(path), "中文内容")

    def test_reads_utf8_without_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text("中文内容", encoding="utf-8")
            self.assertEqual(auto_type.load_payload(path), "中文内容")

    def test_falls_back_to_gb18030_when_not_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text("中文内容", encoding="gb18030")
            self.assertEqual(auto_type.load_payload(path), "中文内容")

    def test_explicit_encoding_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.txt"
            path.write_text("中文内容", encoding="gb18030")
            self.assertEqual(
                auto_type.load_payload(path, encoding="gb18030"), "中文内容"
            )

    def test_missing_file_raises_payload_error(self):
        with self.assertRaises(auto_type.PayloadError):
            auto_type.load_payload(Path("绝对不存在的文件.txt"))


class FakeUser32:
    """Win32 适配层的替身：记录调用，不真的碰键盘。"""

    def __init__(self):
        self.events = []
        self.calls = 0
        self.foreground = 12345
        self.sent_short = False

    def SendInput(self, count, inputs, size):
        self.calls += 1
        for index in range(count):
            ki = inputs[index].union.ki
            self.events.append((inputs[index].type, ki.wVk, ki.wScan, ki.dwFlags))
        return count - 1 if self.sent_short else count

    def GetForegroundWindow(self):
        return self.foreground

    def GetAsyncKeyState(self, vk):
        return 0


def with_fake_user32(fake, body):
    original = auto_type.user32
    auto_type.user32 = fake
    try:
        return body()
    finally:
        auto_type.user32 = original


class TestWindowsAdapter(unittest.TestCase):
    def test_char_is_sent_as_unicode_key_event(self):
        fake = FakeUser32()
        with_fake_user32(
            fake, lambda: auto_type.send_stroke(auto_type.Stroke("char", "中", 0))
        )
        self.assertEqual(len(fake.events), 2)  # 按下 + 抬起
        self.assertEqual([e[2] for e in fake.events], [0x4E2D, 0x4E2D])
        self.assertTrue(all(e[3] & auto_type.KEYEVENTF_UNICODE for e in fake.events))

    def test_surrogate_pair_is_sent_as_two_unicode_key_events(self):
        fake = FakeUser32()
        with_fake_user32(
            fake, lambda: auto_type.send_stroke(auto_type.Stroke("char", "\U0001f600", 0))
        )
        self.assertEqual(len(fake.events), 4)
        self.assertEqual([e[2] for e in fake.events], [0xD83D, 0xD83D, 0xDE00, 0xDE00])
        self.assertEqual(fake.events[0][3], auto_type.KEYEVENTF_UNICODE)
        self.assertEqual(
            fake.events[1][3], auto_type.KEYEVENTF_UNICODE | auto_type.KEYEVENTF_KEYUP
        )

    def test_one_character_is_one_sendinput_call(self):
        """代理对必须一次发完：分两次发会留缝，输入法或目标可能插进来把代理对拆坏。"""
        fake = FakeUser32()
        with_fake_user32(
            fake,
            lambda: (
                auto_type.send_stroke(auto_type.Stroke("char", "中", 0)),
                auto_type.send_stroke(auto_type.Stroke("char", "\U00020bb7", 0)),
            ),
        )
        self.assertEqual(fake.calls, 2)  # 两个字符各一次，而不是按码元拆成三次
        self.assertEqual(len(fake.events), 6)  # 1 码元 × 2 + 2 码元 × 2

    def test_short_send_raises_injection_error(self):
        fake = FakeUser32()
        fake.sent_short = True
        with self.assertRaises(auto_type.InjectionError):
            with_fake_user32(fake, lambda: auto_type.send_stroke(auto_type.Stroke("char", "a", 0)))

    def test_enter_and_backspace_use_virtual_keys(self):
        fake = FakeUser32()
        with_fake_user32(
            fake,
            lambda: (
                auto_type.send_stroke(auto_type.Stroke("enter", "\n", 0)),
                auto_type.send_stroke(auto_type.Stroke("backspace", "\b", 0)),
            ),
        )
        self.assertEqual(fake.events[0][1], auto_type.VK_RETURN)
        self.assertEqual(fake.events[0][3], 0)  # 按下
        self.assertEqual(fake.events[1][3], auto_type.KEYEVENTF_KEYUP)
        self.assertEqual(fake.events[2][1], auto_type.VK_BACK)

    def test_typing_pauses_when_focus_leaves_the_target(self):
        fake = FakeUser32()
        config = auto_type.Config(countdown=0, delay_min=0, delay_max=0, humanize=False)
        statuses = []
        state = {"calls": 0}

        def should_abort():
            state["calls"] += 1
            if state["calls"] == 2:
                fake.foreground = 999  # 焦点被切走
            return state["calls"] >= 4

        result = with_fake_user32(
            fake,
            lambda: auto_type.execute_plan(
                [auto_type.Stroke("char", "a", 0)] * 3,
                config,
                total_chars=3,
                on_status=statuses.append,
                should_abort=should_abort,
            ),
        )
        self.assertTrue(result.aborted)
        self.assertTrue(any("焦点" in s for s in statuses), statuses)


class TestConfigPersistence(unittest.TestCase):
    def test_round_trips_through_json(self):
        config = auto_type.Config(delay_min=25, delay_max=90, humanize=False, jitter=0.5)
        restored = auto_type.Config.from_dict(json.loads(json.dumps(config.to_dict())))
        self.assertEqual(restored, config)

    def test_unknown_keys_are_ignored(self):
        restored = auto_type.Config.from_dict({"delay_min": 40, "这条以后会有": 1})
        self.assertEqual(restored.delay_min, 40)

    def test_dry_run_is_never_persisted(self):
        """干跑是一次性动作，存下来下次开界面会莫名停在"不真敲"。"""
        saved = auto_type.sanitise_for_persistence(auto_type.Config(dry_run=True))
        self.assertFalse(saved.dry_run)

    def test_zero_countdown_is_not_persisted(self):
        """倒计时是安全缓冲：一次 --countdown 0 不该永久取消它。"""
        saved = auto_type.sanitise_for_persistence(auto_type.Config(countdown=0))
        self.assertGreaterEqual(saved.countdown, 1.0)

    def test_normal_countdown_survives(self):
        saved = auto_type.sanitise_for_persistence(auto_type.Config(countdown=10))
        self.assertEqual(saved.countdown, 10)


class TestDryRun(unittest.TestCase):
    def test_dry_run_sends_no_keystrokes(self):
        config = auto_type.Config(
            dry_run=True, countdown=0, delay_min=0, delay_max=0, humanize=False
        )

        class Counter:
            calls = 0

            def SendInput(self, count, inputs, size):
                Counter.calls += 1
                return count

        original = auto_type.user32
        auto_type.user32 = Counter()
        try:
            strokes = auto_type.build_plan("abc", config, rng=random.Random(0))
            result = auto_type.execute_plan(strokes, config, total_chars=3)
        finally:
            auto_type.user32 = original

        self.assertEqual(Counter.calls, 0)
        self.assertEqual(result.typed, len(strokes))
        self.assertFalse(result.aborted)

    def test_dry_run_output_reports_estimated_duration(self):
        config = auto_type.Config(
            dry_run=True, countdown=0, delay_min=10, delay_max=10, humanize=False
        )
        payload = "abc"
        strokes = auto_type.build_plan(payload, config, rng=random.Random(0))
        summary = auto_type.format_dry_run(payload, strokes, config)
        self.assertIn("预计耗时", summary)
        self.assertIn(auto_type.format_duration(auto_type.estimate_seconds(strokes)), summary)

    def test_estimate_seconds_matches_total_waits(self):
        config = auto_type.Config(humanize=False, delay_min=10, delay_max=10)
        strokes = auto_type.build_plan("abcd", config, rng=random.Random(0))
        self.assertAlmostEqual(auto_type.estimate_seconds(strokes), len(strokes) * 10 / 1000)


if __name__ == "__main__":
    unittest.main()
