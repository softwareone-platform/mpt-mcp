from unittest.mock import Mock

import pytest

from mpt_mcp.runtime import runner

PORT = 9090


@pytest.fixture
def uvicorn_run(monkeypatch):
    run_mock = Mock()
    monkeypatch.setattr(runner.uvicorn, "run", run_mock)
    return run_mock


@pytest.mark.parametrize(
    ("debug", "expected"),
    [
        (
            True,
            {"reload": True, "reload_dirs": list(runner.RELOAD_DIRS), "reload_includes": ["*.py"]},
        ),
        (False, {"reload": False, "reload_dirs": None, "reload_includes": None}),
    ],
)
def test_run_uvicorn_reloads_only_with_debug(monkeypatch, uvicorn_run, debug, expected):
    monkeypatch.setattr(runner.config, "debug", debug)

    runner.run_uvicorn(PORT)  # act

    kwargs = uvicorn_run.call_args.kwargs
    assert uvicorn_run.call_args.args == (runner.APP_IMPORT_PATH,)
    assert (kwargs["host"], kwargs["port"]) == (runner.SERVER_HOST, PORT)
    assert {key: kwargs[key] for key in expected} == expected


@pytest.fixture
def startup(monkeypatch):
    steps = Mock()
    monkeypatch.setattr(runner, "configure_logging", steps.configure_logging)
    monkeypatch.setattr(runner, "run_migrations", steps.run_migrations)
    monkeypatch.setattr(runner, "run_uvicorn", steps.run_uvicorn)
    return steps


def test_main_migrates_then_serves_on_port(monkeypatch, startup):
    monkeypatch.setenv("PORT", str(PORT))

    runner.main()  # act

    called = [mock_call[0] for mock_call in startup.mock_calls]
    assert called == ["configure_logging", "run_migrations", "run_uvicorn"]
    startup.run_uvicorn.assert_called_once_with(PORT)


@pytest.mark.parametrize(
    ("error", "exit_code"),
    [(KeyboardInterrupt(), 0), (RuntimeError("boom"), 1)],
)
def test_main_exits_on_stop_or_error(startup, error, exit_code):
    startup.run_uvicorn.side_effect = error

    with pytest.raises(SystemExit) as exit_info:
        runner.main()

    assert exit_info.value.code == exit_code
