# Copyright (c) iGroup.
# All rights reserved.
"""
游乐场状态及奖励边界回归测试。

@author Kai
@date 2026/10/15 14:02
@description 使用临时 SQLite 和模拟 AI，验证存档、扣款、领取与谜底生命周期
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from attendance_helper import db, playground as game
from attendance_helper.activity_store import add_usage_batch, delete_day, set_rule


class PlaygroundTest(unittest.TestCase):
    """
    游乐场在独立数据库中的业务回归。

    @author Kai
    @date 2026/10/15 14:02
    @description 不连接真实 LLM，不修改用户存档
    """

    def setUp(self) -> None:
        """
        为每个案例建立独立数据库。

        @author Kai
        @date 2026/10/15 14:02
        """
        # 临时目录及补丁由清理栈按相反顺序释放。
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # 使用当天中午作为计时基准，避免 mock 全局 time.time 时意外触发跨日口粮。
        self._now = datetime.now().replace(hour=12, minute=0, second=0).timestamp()
        for name, value in (("DB_PATH", Path(temporary.name) / "test.db"), ("_INITIALIZED", False)):
            replacement = patch.object(db, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_allowance_and_restart(self) -> None:
        """
        每日口粮只发一次，重建连接保留余额和偏好。

        @author Kai
        @date 2026/10/15 14:02
        """
        self.assertEqual(game.snapshot()["coins"], 20)
        game.set_preferences(False, "B1")
        tomorrow = date.today() + timedelta(days=1)
        with patch.object(game, "date") as clock:
            clock.today.return_value = tomorrow
            self.assertEqual(game.snapshot()["coins"], 30)
            self.assertEqual(game.snapshot()["coins"], 30)
        db._INITIALIZED = False
        with patch.object(game, "date") as clock:
            clock.today.return_value = tomorrow
            saved = game.snapshot()
        self.assertEqual(saved["coins"], 30)
        self.assertFalse(saved["english"])
        self.assertEqual(saved["level"], "B1")

    def test_trip_only_claimed_once(self) -> None:
        """
        出发时只扣款一次，回家只能领取一次。

        @author Kai
        @date 2026/10/15 14:02
        """
        with patch.object(game.time, "time", return_value=self._now):
            game.start_trip("stall")
            with self.assertRaises(ValueError):
                game.start_trip("shop")
            with self.assertRaises(ValueError):
                game.claim_trip()
        before = game.snapshot()
        self.assertEqual(before["coins"], 15)
        db._INITIALIZED = False
        with patch.object(game.time, "time", return_value=self._now + 61):
            event = game.claim_trip()
            with self.assertRaises(ValueError):
                game.claim_trip()
        after = game.snapshot()
        self.assertEqual(after["coins"], 15 + event["reward"])
        self.assertEqual(after["bag"], [event["item"]])
        self.assertIsNone(after["trip"])
        self.assertEqual(len(after["journal"]), 1)

    def test_insufficient_coins(self) -> None:
        """
        余额不足不能出发，不能透支钱包。

        @author Kai
        @date 2026/10/15 14:02
        """
        for index in range(2):
            with patch.object(game.time, "time", return_value=self._now + index * 1000):
                game.start_trip("shop")
            with patch.object(game.time, "time", return_value=self._now + index * 1000 + 61):
                game.claim_trip()
        with self.assertRaises(ValueError):
            game.start_trip("stall")
        self.assertEqual(game.snapshot()["coins"], 0)

    def test_puzzle_guess_and_reveal_persist(self) -> None:
        """
        提问不直接结束题目，提交正确猜测才结束且可重载。

        @author Kai
        @date 2026/10/15 14:02
        """
        result = {"verdict": "solved", "reply": "正确", "english": "Yes.", "correction": "表达自然"}
        with patch.object(game, "_ask_ai", return_value=result):
            self.assertFalse(game.ask_puzzle("Is it about rain?")["progress"]["solved"])
            saved = game.ask_puzzle("完整猜测", guess=True)
            self.assertTrue(saved["progress"]["solved"])
            with self.assertRaises(ValueError):
                game.ask_puzzle("再问")
        self.assertEqual(len(game.snapshot()["progress"]["messages"]), 2)
        game.reveal_puzzle()
        self.assertTrue(game.snapshot()["progress"]["revealed"])

    def test_bad_ai_does_not_advance(self) -> None:
        """
        网络失败或非法判定不会消耗提问进度。

        @author Kai
        @date 2026/10/15 14:02
        """
        with patch.object(game, "_ask_ai", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                game.ask_puzzle("hello")
        with patch.object(game, "_ask_ai", return_value={"verdict": "wrong-format"}):
            with self.assertRaises(ValueError):
                game.ask_puzzle("hello")
        self.assertEqual(game.snapshot()["progress"]["messages"], [])

    def test_midnight_does_not_submit_against_new_puzzle(self) -> None:
        """
        窗口跨日后不能把旧题问题提交给新题主持。

        @author Kai
        @date 2026/10/15 14:12
        """
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        with patch.object(game, "_ask_ai") as request:
            with self.assertRaises(ValueError):
                game.ask_puzzle("Old question", day=yesterday)
        request.assert_not_called()

    def test_story_failure_keeps_reward_and_retry_cannot_mint_coins(self) -> None:
        """
        讲故事失败不丢奖励，重试生成也不再次发放奖励。

        @author Kai
        @date 2026/10/15 14:02
        """
        with patch.object(game.time, "time", return_value=self._now):
            game.start_trip("explore")
        with patch.object(game.time, "time", return_value=self._now + 121):
            event = game.claim_trip()
        coins = game.snapshot()["coins"]
        with patch.object(game, "_ask_ai", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                game.tell_trip(event["id"])
        self.assertEqual(game.snapshot()["coins"], coins)
        with patch.object(game, "_ask_ai", return_value={"story": "找到藏宝图", "english": "A new map!", "coins": 9999}):
            game.tell_trip(event["id"])
        self.assertEqual(game.snapshot()["coins"], coins)
        self.assertEqual(game.snapshot()["journal"][-1]["english"], "A new map!")

    def test_phrase_dedup_and_practice(self) -> None:
        """
        表达收藏去重，英语纠句使用当前难度和目标表达。

        @author Kai
        @date 2026/10/15 14:02
        """
        game.save_phrase("I'm just looking, thanks.", "随便看看")
        game.save_phrase("I'm just looking, thanks.", "随便看看")
        self.assertEqual(len(game.snapshot()["words"]), 1)
        with patch.object(game, "_ask_ai", return_value={"sentence": "I am just looking.", "explanation": "加上 am。"}) as request:
            result = game.practice_english("I just looking", "I'm just looking, thanks.")
        self.assertIn("I am just looking.", result)
        self.assertIn("A1-A2", request.call_args.args[0])

    def test_usage_theme_respects_manual_categories(self) -> None:
        """
        场景按归类时长选择，手动归类优先且不保留软件名。

        @author Kai
        @date 2026/10/15 14:17
        """
        today = date.today().isoformat()
        add_usage_batch([(today, "exe:code.exe", "私密项目名称", 7200),
                         (today, "rest:idle", "休息", 1800)])
        self.assertEqual(game.usage_context()["scene"], "齿轮工坊")
        set_rule("exe:code.exe", "slack")
        context = game.usage_context()
        self.assertEqual(context["scene"], "灵感集市")
        self.assertEqual(context["growth_target"], 5)
        self.assertNotIn("私密项目名称", str(context))
        self.assertNotIn("code.exe", str(context))

    def test_growth_increment_reclassification_clear_and_cap(self) -> None:
        """
        成长补领只取增量，重新归类和清空不能刷取，每日上限 12。

        @author Kai
        @date 2026/10/15 14:17
        """
        today = date.today().isoformat()
        add_usage_batch([(today, "exe:code.exe", "编辑器", 3600)])
        first = game.claim_growth()
        self.assertEqual(first["growth_gained"], 2)
        self.assertEqual(first["growth"]["traits"]["focus"], 2)
        set_rule("exe:code.exe", "slack")
        with self.assertRaises(ValueError):
            game.claim_growth()
        delete_day(today)
        add_usage_batch([(today, "exe:code.exe", "编辑器", 3600)])
        with self.assertRaises(ValueError):
            game.claim_growth()
        add_usage_batch([(today, "exe:code.exe", "编辑器", 3600 * 20)])
        second = game.claim_growth()
        self.assertEqual(second["growth_gained"], 10)
        self.assertEqual(second["growth"]["xp"], 12)
        self.assertEqual(sum(second["growth"]["traits"].values()), 12)
        with self.assertRaises(ValueError):
            game.claim_growth()

    def test_growth_balanced_allocations_and_unknown(self) -> None:
        """
        工作、娱乐和休息都能成长，未分类不直接发奖。

        @author Kai
        @date 2026/10/15 14:17
        """
        today = date.today().isoformat()
        add_usage_batch([(today, "exe:custom.exe", "未分类", 36000)])
        self.assertEqual(game.usage_context()["growth_target"], 0)
        with self.assertRaises(ValueError):
            game.claim_growth()
        add_usage_batch([(today, "exe:code.exe", "编辑器", 1800),
                         (today, "site:bilibili", "娱乐站点", 1800),
                         (today, "rest:idle", "休息", 1800)])
        result = game.claim_growth()
        self.assertEqual(result["growth"]["traits"], {"focus": 1, "creativity": 1, "vitality": 1})

    def test_trip_uses_departure_usage_without_sending_software_names(self) -> None:
        """
        冒险固定出发背景，发送给模型的只有分类汇总及虚构事件。

        @author Kai
        @date 2026/10/15 14:17
        """
        today = date.today().isoformat()
        add_usage_batch([(today, "exe:code.exe", "机密窗口名称", 3600)])
        with patch.object(game.time, "time", return_value=self._now):
            game.start_trip("explore")
        set_rule("exe:code.exe", "slack")
        with patch.object(game.time, "time", return_value=self._now + 121):
            event = game.claim_trip()
        self.assertEqual(event["usage"]["scene"], "齿轮工坊")
        self.assertEqual(event["item"], "发条罗盘")
        with patch.object(game, "_ask_ai", return_value={"story": "工坊冒险", "english": "A workshop adventure."}) as request:
            game.tell_trip(event["id"])
        payload = request.call_args.args[1]
        self.assertIn("category_minutes", payload)
        self.assertNotIn("机密窗口名称", payload)
        self.assertNotIn("code.exe", payload)

    def test_next_puzzle_keeps_progress_and_counts_once(self) -> None:
        """
        揭晓后可以继续下一题，重复揭晓不重复累计。

        @author Kai
        @date 2026/10/15 15:53
        """
        first = game.snapshot()
        game.reveal_puzzle(first["puzzle_round"])
        game.reveal_puzzle(first["puzzle_round"])
        self.assertEqual(game.snapshot()["puzzle_completed"], 1)
        following = game.next_puzzle(first["puzzle_round"])
        self.assertNotEqual(following["puzzle"]["title"], first["puzzle"]["title"])
        self.assertFalse(following["progress"]["revealed"])
        self.assertEqual(following["puzzle_completed"], 1)
        with self.assertRaises(ValueError):
            game.next_puzzle(first["puzzle_round"])
        with self.assertRaises(ValueError):
            game.reveal_puzzle(first["puzzle_round"])
        self.assertFalse(game.snapshot()["progress"]["revealed"])

    def test_whole_bank_without_repeats_and_safe_reshuffle(self) -> None:
        """
        一轮覆盖全部题目，下一轮不紧接着重复最后一题。

        @author Kai
        @date 2026/10/15 15:53
        """
        seen = set()
        for _ in range(len(game.PUZZLES)):
            current = game.snapshot()
            self.assertNotIn(current["puzzle"]["title"], seen)
            seen.add(current["puzzle"]["title"])
            game.reveal_puzzle()
            following = game.next_puzzle()
        self.assertEqual(len(seen), len(game.PUZZLES))
        self.assertNotEqual(following["puzzle"]["title"], current["puzzle"]["title"])
        self.assertEqual(following["puzzle_completed"], len(game.PUZZLES))
        second_round = set()
        for _ in range(len(game.PUZZLES)):
            current = game.snapshot()
            self.assertNotIn(current["puzzle"]["title"], second_round)
            second_round.add(current["puzzle"]["title"])
            game.reveal_puzzle()
            game.next_puzzle()
        self.assertEqual(second_round, seen)

    def test_unfinished_puzzle_survives_new_day_and_restart(self) -> None:
        """
        不再按日期覆盖正在思考的题目。

        @author Kai
        @date 2026/10/15 15:53
        """
        first = game.snapshot()
        tomorrow = date.today() + timedelta(days=1)
        db._INITIALIZED = False
        with patch.object(game, "date") as clock:
            clock.today.return_value = tomorrow
            following = game.snapshot()
        self.assertEqual(following["puzzle"], first["puzzle"])
        self.assertEqual(following["puzzle_round"], first["puzzle_round"])

    def test_migrate_old_daily_puzzle_preserves_answer(self) -> None:
        """
        扩充题库后保留旧版当天题目和揭晓状态。

        @author Kai
        @date 2026/10/15 15:53
        """
        today = date.today()
        with db.db_conn() as conn:
            state = game._read(conn)
            state["puzzles"][today.isoformat()] = {
                "messages": [], "revealed": True, "solved": False,
            }
            game._write(conn, state)
        migrated = game.snapshot()
        self.assertEqual(migrated["puzzle"]["answer"], game.PUZZLES[today.toordinal() % 5]["answer"])
        self.assertTrue(migrated["progress"]["revealed"])
        self.assertEqual(migrated["puzzle_completed"], 1)

    def test_late_ai_answer_cannot_modify_new_puzzle(self) -> None:
        """
        旧题的异步回答不能混入已经切换的新题。

        @author Kai
        @date 2026/10/15 15:53
        """
        def delayed_result(*_args: object) -> dict[str, str]:
            """
            模拟网络等待期间另一处已揭晓并换题。

            @param _args 模型调用参数
            @return 旧题模型回答
            @author Kai
            @date 2026/10/15 15:53
            """
            game.reveal_puzzle()
            game.next_puzzle()
            return {"verdict": "yes", "reply": "是"}

        with patch.object(game, "_ask_ai", side_effect=delayed_result):
            with self.assertRaises(ValueError):
                game.ask_puzzle("是因为天气吗？")
        self.assertEqual(game.snapshot()["progress"]["messages"], [])


if __name__ == "__main__":
    # 允许直接运行业务回归，不启动托盘进程。
    unittest.main()
