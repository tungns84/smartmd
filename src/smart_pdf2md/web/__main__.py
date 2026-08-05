from __future__ import annotations

import uvicorn

from smart_pdf2md.web.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "smart_pdf2md.web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
