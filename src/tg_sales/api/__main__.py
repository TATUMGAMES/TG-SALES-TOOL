# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""``python -m tg_sales.api``: run the server from environment settings (Docker, hosting).

The local Windows app uses the launcher instead (launch.bat), which also runs
its private PostgreSQL server. Here the database is external
(``TG_SALES_DATABASE_URL``); migrations run at startup after a backup when
``pg_dump`` is available.
"""

from __future__ import annotations

import sys

import uvicorn

from tg_sales.api.app import create_app
from tg_sales.api.context import AppContext
from tg_sales.api.settings import ServerSettings
from tg_sales.config import AppPaths
from tg_sales.errors import TgSalesError
from tg_sales.logging_setup import configure_logging


def main() -> int:
    settings = ServerSettings()
    try:
        settings.check_safe()
        paths = AppPaths.resolve(str(settings.data_dir) if settings.data_dir else None)
        paths.ensure()
        configure_logging(paths.logs_dir)
        context = AppContext(settings, paths)
    except TgSalesError as exc:
        sys.stderr.write(exc.display_text() + "\n")
        return 1
    app = create_app(context, start_scheduler=True)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        proxy_headers=False,
        server_header=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
