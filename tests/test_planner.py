import pytest

from videopip import planner


def test_chunks_fill_exact_total():
    ch = planner.plan_chunks([[(0.0, 10.0)], [(2.0, 8.0)]], 23.0, 3.0, 2.6, 4.0)
    assert abs(sum(d for _, _, d in ch) - 23.0) < 0.02
    assert ch[0] == (0, 3.0, 4.0)
    for ci, s, d in ch:
        rng = [(0.0, 10.0)] if ci == 0 else [(2.0, 8.0)]
        assert any(a - 1e-6 <= s and s + d <= b + 1e-6 for a, b in rng)


def test_forced_take_follows_reveal_and_is_not_replayed():
    ch = planner.plan_chunks([[(0.0, 30.0)]], 20.0, 1.0, 2.6, 4.0, forced=[(0, 15.0, 5.0)])
    assert ch[1] == (0, 15.0, 5.0)
    for _, s, d in ch[2:]:
        assert s + d <= 15.0 + 1e-6 or s >= 20.0 - 1e-6


def test_forced_outside_safe_raises():
    with pytest.raises(planner.PlanError):
        planner.plan_chunks([[(0.0, 10.0)]], 10.0, 1.0, 2.6, forced=[(0, 8.0, 5.0)])


def test_montage_cues_follow_sentences_and_clamp():
    shots = [("hero", 11.0, None), ("cue", 4.0, None), ("cue", 4.5, None), ("cue", 5.0, None),
             ("music", 4.0, 4.0), ("music", 1.4, 1.4), ("music", 4.0, None)]
    plan = planner.plan_montage(shots, [0.0, 3.1, 6.0, 9.2], 12.0, cold_gap=1.2, hero_hold=4.5,
                                vo_deadline=15.0, cue_lead=0.35, sub_at=15.0, sub_len=8.52, intro_len=None)
    assert plan.lengths[1] == pytest.approx(1.2 + 6.0 - 0.35 - 4.5, abs=0.02)
    assert all(l <= c + 0.05 for l, (_, c, _) in zip(plan.lengths, shots))
    assert plan.starts[4] == pytest.approx(15.0, abs=0.02)
    assert plan.total == pytest.approx(15.0 + 8.52, abs=0.05)


def test_montage_vo_deadline():
    with pytest.raises(planner.PlanError):
        planner.plan_montage([("hero", 20.0, None)], [0.0], 16.0, cold_gap=1.2, hero_hold=4.5,
                             vo_deadline=15.0, cue_lead=0.35, sub_at=None, sub_len=0, intro_len=None)


def test_hero_too_short_raises():
    with pytest.raises(planner.PlanError):
        planner.plan_montage([("hero", 3.0, None)], [0.0], 5.0, cold_gap=1.2, hero_hold=4.5,
                             vo_deadline=15.0, cue_lead=0.35, sub_at=12.0, sub_len=5.0, intro_len=None)


def test_xfade_offsets():
    ds, offs, total = planner.xfade_offsets([10.0, 20.0, 5.0], 0.5)
    assert offs == [9.5, 29.0]
    assert total == pytest.approx(34.0)
