"""Minimal CLI entry point for the OBS Code Harness runtime."""

from __future__ import annotations

import typer
import uvicorn

from config.config import load_config
from desktop_app import run_desktop_app


def create_fastapi_app():
    """Return the single FastAPI app used by the Harness runtime."""
    from api import app as api_app

    return api_app


fastapi_app = create_fastapi_app()

app = typer.Typer(
    name="obs-code",
    help="OBS Code Harness runtime",
    add_completion=False,
)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload", help="Enable code reload."),
) -> None:
    """Run the FastAPI Harness service."""
    config = load_config()
    actual_port = port or getattr(config, "api_port", 8000)
    uvicorn.run(
        "api:app",
        host=host,
        port=actual_port,
        reload=reload,
        reload_dirs=["src", "ui"] if reload else None,
        access_log=False,
    )


@app.command()
def desktop() -> None:
    """Run the desktop shell that hosts the same Harness web UI."""
    run_desktop_app()


if __name__ == "__main__":
    app()
