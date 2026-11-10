"""Inside WSL PyNMR uses Qt's xcb backend unless told otherwise (unh/lab_env.py, feature lab-env)."""
from unh.lab_env import in_wsl, prefer_xcb_on_wsl


def proc(tmp_path, text):
    p = tmp_path / 'version'
    p.write_text(text)
    return str(p)


def test_wsl_with_a_display_gets_xcb(tmp_path):
    env = {'DISPLAY': ':0', 'WSL_DISTRO_NAME': 'Ubuntu'}
    assert prefer_xcb_on_wsl(env, 'linux', proc(tmp_path, 'Linux version 5.15')) == 'xcb'
    assert env['QT_QPA_PLATFORM'] == 'xcb'
    env = {'DISPLAY': ':0'}                                          # no WSL variables: /proc/version tells
    assert prefer_xcb_on_wsl(env, 'linux', proc(tmp_path, 'Linux version 5.15.167.4-microsoft-standard-WSL2')) == 'xcb'


def test_left_alone_elsewhere_or_when_set(tmp_path):
    native = proc(tmp_path, 'Linux version 6.8.0-45-generic (buildd@lcy02)')
    env = {'DISPLAY': ':0'}
    assert prefer_xcb_on_wsl(env, 'linux', native) is None and 'QT_QPA_PLATFORM' not in env   # ordinary Linux
    env = {'DISPLAY': ':0', 'WSL_DISTRO_NAME': 'Ubuntu'}
    assert prefer_xcb_on_wsl(env, 'win32') is None and 'QT_QPA_PLATFORM' not in env           # Windows
    env = {'DISPLAY': ':0', 'WSL_DISTRO_NAME': 'Ubuntu', 'QT_QPA_PLATFORM': 'wayland'}
    assert prefer_xcb_on_wsl(env, 'linux') is None and env['QT_QPA_PLATFORM'] == 'wayland'    # operator's choice
    env = {'WSL_DISTRO_NAME': 'Ubuntu'}
    assert prefer_xcb_on_wsl(env, 'linux') is None and 'QT_QPA_PLATFORM' not in env           # no X display
    assert not in_wsl({}, 'linux', str(tmp_path / 'missing'))
