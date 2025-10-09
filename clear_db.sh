#!/bin/bash

redis-cli FLUSHDB
psql -d knightmare -c "TRUNCATE TABLE users, games, moves RESTART IDENTITY CASCADE;"