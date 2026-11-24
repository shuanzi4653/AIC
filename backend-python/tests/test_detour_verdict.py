"""绕飞与裁决的护栏（V1.1.4）。

背景：2026-11-24 实测到"能绕的判红、绕不开的放行"。
  · `_risk` 里 `if detour: risk += 0.18` —— 端点能见度 1.4 km 的基础分是 0.72（仅提示），
    一有绕飞就变 0.90 → HIGH，标签被染红；实测 NC-0211 / NC-0038 就是这样。
  · 真实模式 `blocked_ids` 恒为空 —— 压线又绕不开的走廊被当成直飞放行，
    而"停飞（无可用绕飞方案）"这句只在演示包里出现。
这两条都是"方向反了"，用断言把方向钉死。

只用标准库：nation_ops 除 zlib 外没有第三方依赖。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from traffic import nation_ops  # noqa: E402


def _row(**over) -> dict:
    base = {'id': 'NC-9999', 'fromName': '甲市', 'toName': '乙市',
            'fromLonLat': [115.0, 30.0], 'toLonLat': [116.0, 29.7],
            'lengthKm': 108.5, 'kind': 'AIRPORT_FEED', 'fromProvince': '甲省', 'toProvince': '乙省'}
    base.update(over)
    return base


# 端点 1.4 km：VIS_BANDS 第一档 1500 m → 0.72，低于 RISK_HOLD(0.75)，本身不该停飞
_WEATHER_LOW_VIS = {'甲市': {'visM': 1400}, '乙市': {'visM': 1400}}
_DETOUR = {'path': [[115.0, 30.0], [115.6, 29.4], [116.0, 29.7]], 'shiftKm': 12.0, 'hitKm': 30.0}


class DetourIsDisposalNotRisk(unittest.TestCase):

    def test_detour_does_not_raise_risk(self):
        plain = nation_ops._risk(_row(), _WEATHER_LOW_VIS, None, None)
        with_detour = nation_ops._risk(_row(), _WEATHER_LOW_VIS, _DETOUR, None)
        self.assertEqual(plain['riskP'], with_detour['riskP'],
                         '绕飞不应改变风险分：它是处置，不是风险源')
        self.assertLess(with_detour['riskP'], nation_ops.RISK_HOLD,
                        '能见度 1.4 km 属于"提示"档，绕飞不该把它推过停飞线')

    def test_detour_is_released_not_held(self):
        got = nation_ops._risk(_row(), _WEATHER_LOW_VIS, _DETOUR, None)
        self.assertEqual(got['decision'], 'DETOUR')
        self.assertEqual(got['decisionLabel'], '绕飞放行')

    def test_detour_still_shows_up_in_drivers(self):
        got = nation_ops._risk(_row(), _WEATHER_LOW_VIS, _DETOUR, None)
        joined = ' '.join(got['drivers'])
        self.assertIn('绕飞', joined, '绕飞必须留在依据里，读者要看得到外偏多少')


class HitThreshold(unittest.TestCase):
    """nation.py 依赖 pyproj / shapely，没装的环境 import 会炸 —— 所以这两条读源码字符串，
    与前端那批护栏同一个办法（`node --test` 也是读源码）。"""

    SRC = (Path(__file__).resolve().parents[1] / 'traffic' / 'nation.py').read_text(encoding='utf-8')

    def test_min_hit_km_is_declared(self):
        self.assertIn('MIN_HIT_KM = 3.0', self.SRC, '压线门槛要单点声明，别散在各个调用处')

    def test_detour_table_returns_blocked_set(self):
        """真实模式也要产出 blocked —— 以前只在虚拟气象里算，正式环境永远不封锁。"""
        start = self.SRC.index('def _detour_table')
        body = self.SRC[start:self.SRC.index('def ', start + 10)]
        self.assertIn('blocked', body)
        self.assertIn('_hit_km', body, '压线判定要按贯穿长度，不能只看 intersects')
        self.assertIn('return table, blocked', body)

    def test_edges_are_not_treated_as_crossing(self):
        start = self.SRC.index('def _detour_for')
        body = self.SRC[start:self.SRC.index('def ', start + 10)]
        self.assertIn('MIN_HIT_KM', body, '擦边（<3 km 贯穿）不该生成绕飞方案')


if __name__ == '__main__':
    unittest.main(verbosity=2)
