import os

from thumbnail_studio import create_app


app = create_app()


if __name__ == "__main__":
    app.run(
        debug=True,
        host="127.0.0.1",
        port=int(os.getenv("APP_PORT", "5001")),
    )
