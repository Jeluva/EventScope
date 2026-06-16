#!/usr/bin/env sh
set -e
eventscope init-db
eventscope ingest
eventscope purge
