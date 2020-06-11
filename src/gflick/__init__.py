# It's a shame we can't just install a shell script to run the
# gunicorn cli because poetry doesn't support that yet:
# https://github.com/python-poetry/poetry/issues/241
import subprocess


def prod():
    subprocess.run(
        ["gunicorn", "gflick.server:app", "--workers=5", "--bind=127.0.0.1:8000"]
    )


def dev():
    import os

    subprocess.run(
        [
            "gunicorn",
            "gflick.server:app",
            "--workers=5",
            "--bind=127.0.0.1:8000",
            "--reload",
        ],
        env={**os.environ, "GFLICK_DEBUG": "1"},
    )


def raw():
    import bottle
    from .server import app

    bottle.run(app, port=8000)


def google():
    from .google import main

    main()
