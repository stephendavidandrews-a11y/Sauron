"""Assembled SQL schema from domain modules.

Each module exports a single SQL string. This __init__ combines them
in dependency order (core tables first, then tables that reference them).
"""

from sauron.db.tables.core import CORE_SQL
from sauron.db.tables.speakers import SPEAKERS_SQL
from sauron.db.tables.intelligence import INTELLIGENCE_SQL
from sauron.db.tables.corrections import CORRECTIONS_SQL
from sauron.db.tables.operations import OPERATIONS_SQL
from sauron.db.tables.text import TEXT_SQL
from sauron.db.tables.routing import ROUTING_SQL
from sauron.db.tables.entities import ENTITIES_SQL

# Combined SQL for fresh installs (order matters for foreign keys)
ALL_TABLES_SQL = (
    CORE_SQL
    + SPEAKERS_SQL
    + INTELLIGENCE_SQL
    + CORRECTIONS_SQL
    + OPERATIONS_SQL
    + TEXT_SQL
    + ROUTING_SQL
    + ENTITIES_SQL
)
