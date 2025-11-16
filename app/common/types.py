# backend/app/common/types.py

from typing import Annotated, Optional
from sqlalchemy import BIGINT, VARCHAR, BOOLEAN, text
from sqlalchemy.orm import mapped_column

# --- Primary Keys ---
# Reusable type for integer primary keys.
int_pk = Annotated[int, mapped_column(BIGINT, primary_key=True, autoincrement=True)]
# Reusable type for the string-based primary key for the Game table.
str_pk_10 = Annotated[str, mapped_column(VARCHAR(10), primary_key=True)]

# --- Standard Columns ---
# Reusable types for common string lengths.
str_10 = Annotated[str, mapped_column(VARCHAR(10), nullable=False)]
str_50 = Annotated[str, mapped_column(VARCHAR(50), nullable=False, unique=True)]
str_100 = Annotated[str, mapped_column(VARCHAR(100), nullable=False)]
str_255 = Annotated[str, mapped_column(VARCHAR(255), nullable=False)]

# Reusable type for an optional string.
optional_str_10 = Annotated[Optional[str], mapped_column(VARCHAR(10))]

# Reusable type for a boolean that defaults to false.
bool_false = Annotated[
    bool, mapped_column(BOOLEAN, server_default=text("false"), nullable=False)
]
