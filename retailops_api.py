"""Compatibility imports and private entrypoint; implementation lives in retailops/."""
from retailops.core import ApiError, ROOT, REASONS, STATUSES, fields, require
from retailops.business.store import BusinessStore
from retailops.business.application import Application
from retailops.http.routes import api_result
from retailops.http.private import Handler, Server

def main():
    from retailops.bootstrap import serve_private
    serve_private()

if __name__ == '__main__':
    main()
