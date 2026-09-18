from threading import Timer
import webbrowser

import uvicorn


APP_URL = "http://localhost:8000"


def open_browser() -> None:
    webbrowser.open(APP_URL)


if __name__ == "__main__":
    Timer(
        1.5,
        open_browser,
    ).start()

    uvicorn.run(
        "app.main:app",
        host="localhost",
        port=8000,
        reload=False,
        log_level="info",
    )