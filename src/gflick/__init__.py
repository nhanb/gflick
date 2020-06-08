def prod():
    from .server import run_prod

    run_prod()


def dev():
    from .server import run_dev

    run_dev()


def google():
    from .google import main

    main()
