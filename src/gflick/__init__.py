def prod():
    from gflick import db
    import uvicorn

    db.init()
    uvicorn.run("gflick.server:app", host="127.0.0.1", port=8000, log_level="info")


def dev():
    from gflick import db
    import uvicorn

    db.init()
    uvicorn.run(
        "gflick.server:app", host="127.0.0.1", port=8000, log_level="info", reload=True
    )


def google():
    from .google import main

    main()
