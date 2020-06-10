def prod():
    from gflick import db
    import uvicorn

    db.init()
    uvicorn.run("gflick.server:app", host="localhost", port=8000, log_level="info")


def dev():
    from gflick import db
    import uvicorn
    import os

    os.environ["GFLICK_DEBUG"] = "1"

    db.init()
    uvicorn.run(
        "gflick.server:app", host="localhost", port=8000, log_level="info", reload=True
    )


def google():
    from .google import main

    main()
