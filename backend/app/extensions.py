"""
Flask extension instances.

Extensions are instantiated here (without an app) and then initialised
inside the application factory via ``init_app``.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS

db = SQLAlchemy()
migrate = Migrate()
cors = CORS()
