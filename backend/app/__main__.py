import logging
import sys

from .config import Settings
from .db import Database, migrate
from .server import App, make_server


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        s = Settings()
        s.ensure_dirs()
        applied = migrate(Database(s.db_path))
        print("Applied migrations: %s" % (", ".join(applied) or "none (already up to date)"))
        return
    app = App()
    srv = make_server(app)
    print("Serving on http://%s:%d  (env=%s, data=%s)" % (app.settings.host, srv.server_address[1], app.settings.env, app.settings.data_dir))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
