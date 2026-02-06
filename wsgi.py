#!/usr/bin/env python3
"""
WSGI entry point for Harmony Hub Web Controller.
Used by gunicorn in production deployments.
"""
from app import app

if __name__ == "__main__":
    app.run()
