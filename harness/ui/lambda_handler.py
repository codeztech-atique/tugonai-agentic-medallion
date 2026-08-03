"""AWS Lambda entrypoint for the Agent Console API (Mangum + FastAPI)."""

from mangum import Mangum

from app import app

handler = Mangum(app, lifespan="off")
