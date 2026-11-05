from jarvis.webui.selfcheck import Facts, evaluate, render


def levels(f):
    return {name: lvl for lvl, name, _ in evaluate(f)}


GOOD = dict(dist_ready=True, hello=True, webgl="webgl2", renderer="NVIDIA GeForce RTX 3060", canvas_ok=True, live_data=True, fps=60.0)


def test_healthy_machine_passes_everything():
    r = evaluate(Facts(**GOOD))
    assert all(lvl == "PASS" for lvl, _, _ in r)
    assert "RESULT: OK (0 failed, 0 warnings)" in render(r)


def test_software_rendering_is_a_warning_not_a_failure():
    lv = levels(Facts(**{**GOOD, "renderer": "Google SwiftShader", "fps": 8.0}))
    assert lv["WebGL"] == "WARN" and lv["Smoothness"] == "FAIL"
    assert levels(Facts(**{**GOOD, "renderer": "Microsoft Basic Render Driver"}))["WebGL"] == "WARN"


def test_missing_pieces_fail_with_plain_words():
    f = Facts(dist_ready=False, hello=False, webgl=None, canvas_ok=False, live_data=False, fps=None)
    lv = levels(f)
    assert lv["UI bundle"] == lv["Backend link"] == lv["WebGL"] == lv["Hologram canvas"] == "FAIL"
    assert lv["Live data"] == "WARN" and lv["Smoothness"] == "WARN"
    assert "NOT READY" in render(evaluate(f))


def test_smoothness_bands():
    assert levels(Facts(**{**GOOD, "fps": 30.0}))["Smoothness"] == "WARN"
    assert levels(Facts(**{**GOOD, "fps": 19.0}))["Smoothness"] == "FAIL"
    assert levels(Facts(**{**GOOD, "fps": 45.0}))["Smoothness"] == "PASS"
