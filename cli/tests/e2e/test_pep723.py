"""PEP 723 E2E coverage for committed and lockless script environments.

``examples/simple_script`` exercises a pre-existing script lock. The lockless
case uses a local pure-Python wheel while offline, proving that uvloom invokes
``uv lock --script`` without depending on mutable public-index resolution.
"""

import json
import os
import tomllib


EXPECTED = "Hello from a uv inline-dependency script!"
LOCAL_WHEEL_EXPECTED = "local-wheel-ok:0.1"


def test_run_script_with_existing_lock(make_project, run_uvloom):
    project = make_project("examples/simple_script")
    assert (project / "script.py.lock").is_file()

    res = run_uvloom(project, "run", "script.py", check=True, timeout=3600)
    assert EXPECTED in res.stdout, (
        f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
    )


def test_run_script_locks_local_wheel_offline(make_project, run_uvloom):
    project = make_project("cli/tests/fixtures/pep723_local_wheel")
    script = project / "script.py"
    wheel = project / "local_demo-0.1-py3-none-any.whl"
    lock = project / "script.py.lock"
    assert not lock.exists()

    # Fixture stays relocatable in git. PEP 508 direct references need an
    # absolute URI, so create it after the fixture is copied to tmp_path.
    script.write_text(
        script.read_text().replace(
            'dependencies = []',
            f'dependencies = ["local-demo @ {wheel.resolve().as_uri()}"]',
        )
    )

    res = run_uvloom(
        project,
        "run",
        "script.py",
        env={"UV_OFFLINE": "1"},
        check=True,
        timeout=3600,
    )
    assert lock.is_file(), "script lock was not auto-created"
    assert "uv lock --script" in res.stderr, (
        f"expected auto-lock notice on stderr; got:\n{res.stderr}"
    )
    assert LOCAL_WHEEL_EXPECTED in res.stdout

    data = tomllib.loads(lock.read_text())
    packages = data["package"]
    assert len(packages) == 1
    assert packages[0]["name"] == "local-demo"
    # uv owns this absolute-path lock; uvloom must not rewrite it in place.
    assert packages[0]["source"] == {"path": str(wheel.resolve())}
    uvloom_dir = project / ".uvloom"
    assert not list(uvloom_dir.glob("*.uv2nix.lock"))

    projected_locks = list(uvloom_dir.glob("*.attempt-*/*.uv2nix.lock"))
    assert len(projected_locks) == 1
    projected_lock = projected_locks[0]
    attempt_dir = projected_lock.parent
    assert (attempt_dir / script.name).read_text() == script.read_text()
    assert tomllib.loads(projected_lock.read_text())["package"][0]["source"] == {
        "path": os.path.join("local-sources", "0-path", wheel.name)
    }

    marker = json.loads((project / "script.py.uvloom.json").read_text())
    assert set(marker) == {"key", "store_path", "cli_version"}
    assert os.path.exists(marker["store_path"])
    out_links = list(uvloom_dir.glob("*.venv"))
    assert len(out_links) == 1
    assert os.readlink(out_links[0]) == marker["store_path"]
