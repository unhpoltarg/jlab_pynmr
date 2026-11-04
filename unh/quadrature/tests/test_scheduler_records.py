"""Scheduler sequences and tags, settings loading, record helpers. No Qt, no hardware."""
import datetime
import json
import os
import sys
import types

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from unh.quadrature import records, settings
from unh.quadrature.scheduler import Scheduler

T0 = datetime.datetime(2026, 10, 27, 12, 0, 0, tzinfo=datetime.timezone.utc)


def sched(seq=(0, 90)):
    s = Scheduler(list(seq), 1.0)
    s.tunes[0], s.tunes[90] = 0.238, 0.4076
    return s


def test_inactive_adds_nothing_and_writes_dac_only_to_restore_real():
    s = sched()
    a = s.next_assignment(0.238)
    assert a.tags == {} and a.angle == 0 and not a.write_dac
    a = s.next_assignment(0.4076)          # Tune tab left on Imag: run starts back on the Real tune
    assert a.tags == {} and a.vout == 0.238 and a.write_dac


def test_pair_sequence_groups_and_tags():
    s = sched()
    s.active = True
    s.start_run(T0)
    got = [s.next_assignment(0.238) for _ in range(5)]
    assert [a.angle for a in got] == [0, 90, 0, 90, 0]
    assert [a.vout for a in got] == [0.238, 0.4076, 0.238, 0.4076, 0.238]
    assert all(a.write_dac for a in got)
    assert [a.tags['quad_group'] for a in got] == ['2026-10-27_12-00-00_0001'] * 2 + ['2026-10-27_12-00-00_0002'] * 2 + \
        ['2026-10-27_12-00-00_0003']
    assert [a.tags['quad_index'] for a in got] == [0, 1, 0, 1, 0]
    t = got[1].tags
    assert t['quad_mode'] == 'pair' and t['quad_ref_deg'] == 90 and t['quad_vout'] == 0.4076
    assert t['quad_tunes'] == {'0': 0.238, '90': 0.4076} and t['quad_state'] == 'ok'
    json.dumps(t)                          # JSON-clean


def test_abba_and_restart():
    s = sched(settings.SEQUENCES['abba'])
    s.active = True
    s.start_run(T0)
    assert [s.next_assignment(0.238).angle for _ in range(8)] == [0, 90, 90, 0] * 2
    s.start_run(T0)
    assert s.next_assignment(0.238).tags['quad_group'].endswith('_0001')


def test_dac_failure_suspends_to_real():
    s = sched()
    s.active = True
    s.start_run(T0)
    a = s.next_assignment(0.238)
    s.dac_written(a, False)
    assert s.suspended
    b = s.next_assignment(0.238)
    assert b.angle == 0 and b.vout == 0.238 and b.tags['quad_state'] == 'suspended'


def test_missing_tunes():
    s = Scheduler([0, 90, 180, 270], 1.0)
    s.tunes[0] = 0.2
    assert s.missing_tunes() == [90, 180, 270]


def test_calibration_tags_and_validity():
    s = sched()
    s.calibration = {'cal_id': 'C1', 'channel': 'Deuteron5T', 'tunes': {'0': 0.238, '90': 0.4076},
                     'fit': {'success': True, 'v_real': 0.238, 'gain_coeffs': [0.1],
                             'phi_table': {'vout': [0.0, 0.238, 0.4076, 0.9], 'phi_deg': [-50.0, 0.0, 89.5, 300.0]}}}
    s.active = True
    s.start_run(T0)
    s.next_assignment(0.238)
    t = s.next_assignment(0.238).tags
    assert t['quad_cal_id'] == 'C1' and t['quad_cal_angle_deg'] == pytest.approx(89.5)
    assert t['quad_cal_gain'] == pytest.approx(1 + 0.1 * (0.4076 - 0.238))
    assert t['quad_cal_valid'] is True
    s.tunes[90] = 0.41                     # operator retuned Imag after the calibration
    assert not s.calibration_valid()
    assert s.calibration_valid() is False and s.calibration_valid('Deuteron5T') is False


def test_settings_defaults_off_and_profile_override(tmp_path):
    assert settings.load_settings(path=str(tmp_path / 'missing.yaml'))['enable'] is False
    p = tmp_path / 'q.yaml'
    p.write_text('enable: False\nsequence: abba\ncal: {steps: 21}\nprofiles:\n  X: {enable: True, settle_ms: 2}\n')
    cfg = settings.load_settings('X', str(p))
    assert cfg['enable'] is True and cfg['settle_ms'] == 2.0 and cfg['cal']['steps'] == 21
    assert settings.sequence_of(cfg) == [0, 90, 90, 0]
    assert settings.load_settings('Y', str(p))['enable'] is False
    p.write_text('enable: True\nsequence: [90, 180]\n')
    assert settings.load_settings(None, str(p))['enable'] is False          # no 0 in the sequence


def test_shipped_settings_on_only_for_deuteron_and_test_profile():
    assert settings.load_settings(None)['enable'] is False
    assert settings.load_settings('Proton')['enable'] is False          # its shifter covers only 180 deg
    assert settings.load_settings('Deuteron')['enable'] is True         # on for the hall since 2026-11-04
    assert settings.load_settings('TestSimQuad')['enable'] is True


def test_group_baselines_per_angle():
    events = {
        'a': {'phase': [1.0, 1.0], 'sweeps': 100, 'quad_ref_deg': 0, 'label': 'Baseline'},
        'b': {'phase': [5.0, 5.0], 'sweeps': 100, 'quad_ref_deg': 90, 'label': 'Baseline'},
        'c': {'phase': [3.0, 3.0], 'sweeps': 300, 'quad_ref_deg': 0, 'label': 'Baseline'},
    }
    out = records.group_baselines(events, ['a', 'b', 'c'])
    assert sorted(out) == [0, 90]
    assert np.allclose(out[0]['phase'], 2.5) and out[0]['sweeps'] == 400 and out[0]['base_stamps'] == ['a', 'c']
    assert np.allclose(out[90]['phase'], 5.0) and out[90]['quad_ref_deg'] == 90
    plain = {'x': {'phase': [1.0], 'sweeps': 10}}
    assert records.group_baselines(plain, ['x']) is None


def test_is_real_and_tagging():
    e = types.SimpleNamespace()
    assert records.is_real(e)
    records.tag_event(e, {'quad_ref_deg': 90})
    assert not records.is_real(e) and records.angle_of({'quad_ref_deg': 270}) == 270


def test_calibration_file_round_trip(tmp_path):
    rec = {'record_type': 'quad_calibration', 'cal_id': '2026-10-27_12-00-00', 'channel': 'Deuteron5T',
           'x': np.float64(1.5), 'arr': np.arange(3), 'bad': float('nan')}
    path = records.write_calibration(rec, str(tmp_path / 'quad_cal'))
    back = records.latest_calibration(str(tmp_path / 'quad_cal'), 'Deuteron5T')
    assert back['x'] == 1.5 and back['arr'] == [0, 1, 2] and back['bad'] is None
    assert records.latest_calibration(str(tmp_path / 'quad_cal'), 'Proton') is None
    assert os.path.basename(path) == '2026-10-27_12-00-00.json'

def test_calibration_is_stale_at_another_centre_frequency():
    s = sched()
    s.calibration = {'cal_id': 'C1', 'channel': 'Deuteron5T', 'cent_freq': 32.7, 'tunes': {'0': 0.238, '90': 0.4076},
                     'fit': {'success': True, 'v_real': 0.238, 'gain_coeffs': [],
                             'phi_table': {'vout': [0.0, 0.238, 0.4076, 0.9], 'phi_deg': [-50.0, 0.0, 89.5, 300.0]}}}
    s.context = {'channel': 'Deuteron5T', 'cent_freq': 32.7}
    assert s.calibration_valid()
    s.context = {'channel': 'Deuteron5T', 'cent_freq': 22.0}      # the shifter's curve is frequency dependent
    assert not s.calibration_valid()
    s.active = True
    s.start_run(T0)
    assert s.next_assignment(0.238).tags['quad_cal_valid'] is False


def test_group_baselines_never_mixes_tunes():
    events = {
        'a': {'phase': [1.0], 'sweeps': 64, 'quad_ref_deg': 90, 'phase_vout': 0.444},   # before a retune
        'b': {'phase': [3.0], 'sweeps': 64, 'quad_ref_deg': 90, 'phase_vout': 0.4076},
        'c': {'phase': [5.0], 'sweeps': 64, 'quad_ref_deg': 90, 'phase_vout': 0.4076},
        'd': {'phase': [7.0], 'sweeps': 64, 'quad_ref_deg': 0, 'phase_vout': 0.5063},
    }
    out = records.group_baselines(events, ['a', 'b', 'c', 'd'])
    assert np.allclose(out[90]['phase'], 4.0) and out[90]['base_stamps'] == ['b', 'c']
    assert out[90]['dropped_stamps'] == ['a'] and out[90]['phase_vout'] == 0.4076
    assert out[0]['dropped_stamps'] == [] and out[0]['phase_vout'] == 0.5063
