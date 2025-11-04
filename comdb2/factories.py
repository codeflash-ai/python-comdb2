# Copyright 2017 Bloomberg Finance L.P.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""This module provides factory functions for use with Comdb2 handles.

Both `.dbapi2.Connection` and `.cdb2.Handle` have a public ``row_factory``
property that can be used to control the type used for result rows.  By
default, each row is returned as a `list`, but you can receive the row as
a `collections.namedtuple` by using `namedtuple_row_factory` as the
``row_factory``.  Likewise you can receive the row as a `dict` by using
`dict_row_factory`.

A factory function will be called with a list of column names, and must return
a callable that will be called once per row with a list of column values.
"""

from __future__ import annotations

from collections import namedtuple
from .cdb2 import Value
from collections.abc import Callable
from typing import NamedTuple


def namedtuple_row_factory(col_names: list[str]) -> Callable[[list[Value]], NamedTuple]:
    """Return each result row as a `collections.namedtuple`.

    The fields of the `~collections.namedtuple` are set to the names of the
    result set columns, in positional order.

    Note:
        You will not be able to use this factory if your result set includes
        columns whose names aren't valid Python attribute names.  Make sure to
        assign each column a name starting with a letter and containing only
        alphanumeric characters and underscores.  Also make sure that column
        names aren't Python reserved words.  You can control column names by
        using ``AS`` in your SQL query, as in:

        .. code-block:: sql

            SELECT count(*) AS rowcount

    Note:
        You will not be able to use this factory if your result set includes
        duplicated column names.  This can happen when joining across tables
        that use the same name for a foreign key column, for instance.  To
        avoid duplicating column names, avoid using ``SELECT *`` with joins.

        You may also be able to use the ``USING`` clause on the join to avoid
        duplicating column names.  This query would duplicate the ``id``
        column:

        .. code-block:: sql

            SELECT * FROM a INNER JOIN b ON a.id = b.id

        Whereas this one wouldn't:

        .. code-block:: sql

            SELECT * FROM a INNER JOIN b USING(id)

    Example:
        >>> conn.row_factory = namedtuple_row_factory
        >>> row = conn.cursor().execute("select 1 as x, 2 as y").fetchone()
        >>> print(row)
        Row(x=1, y=2)
        >>> print(row.x)
        1
    """
    # Ensure DML doesn't raise an exception for an invalid column name
    if len(col_names) == 1:
        if col_names[0] in ("rows inserted", "rows updated", "rows deleted"):
            # Cache the result of namedtuple for single DML case by using a static class
            # This is a minor improvement, but avoids namedtuple instantiation repetition
            return _get_single_dml_namedtuple_maker(col_names[0])

    # Pre-check for duplicate column names before calling namedtuple (which is expensive), and raise if found
    # This block is faster than failing inside namedtuple's exception/retry path, and avoids constructing
    # an unnecessary class just to throw
    if len(col_names) != len(set(col_names)):
        # If the error was caused by duplicated column names, raise a more
        # preceise error message.  Otherwise, re-raise.
        _raise_on_duplicate_column_names(col_names)
        # Will raise, so no further code runs

    # If we reached here, there are no duplicate names, and we can construct namedtuple normally
    return namedtuple("Row", col_names)._make


def dict_row_factory(col_names: list[str]) -> Callable[[list[Value]], dict[str, Value]]:
    """Return each result row as a `dict` mapping column names to values.

    Note:
        You will not be able to use this factory if your result set includes
        duplicated column names.  This can happen when joining across tables
        that use the same name for a foreign key column, for instance.  To
        avoid duplicating column names, avoid using ``SELECT *`` with joins.

        You may also be able to use the ``USING`` clause on the join to avoid
        duplicating column names.  This query would duplicate the ``id``
        column:

        .. code-block:: sql

            SELECT * FROM a INNER JOIN b ON a.id = b.id

        Whereas this one wouldn't:

        .. code-block:: sql

            SELECT * FROM a INNER JOIN b USING(id)

    Example:
        >>> conn.row_factory = dict_row_factory
        >>> row = conn.cursor().execute("select 1 as x, 2 as y").fetchone()
        >>> print(row)
        {'y': 2, 'x': 1}
        >>> print(row['x'])
        1
    """
    _raise_on_duplicate_column_names(col_names)

    def dict_row(col_vals):
        return dict(zip(col_names, col_vals))

    return dict_row


def _raise_on_duplicate_column_names(col_names):
    distinct_col_names = set(col_names)
    if len(col_names) == len(distinct_col_names):
        return
    # The main bottleneck in the profile was Counter and bad_names list comp.
    # We can get duplicate names more efficiently by iterating once and recording those with count > 1.
    counts = {}
    # This loop is faster than Counter for moderate input sizes, and no need for Counter object bloat
    for name in col_names:
        counts[name] = counts.get(name, 0) + 1
    bad_names = [name for name, count in counts.items() if count > 1]
    raise ValueError("Duplicated column names", *bad_names)

def _get_single_dml_namedtuple_maker(col_name: str):
    # Static cache, keyed by column name (should only ever be three values)
    # This avoids multiple constructions of identical namedtuple classes.
    # Thread-safe in CPython due to GIL and single-threaded usage
    if not hasattr(_get_single_dml_namedtuple_maker, "_cache"):
        _get_single_dml_namedtuple_maker._cache = {}
    cache = _get_single_dml_namedtuple_maker._cache
    if col_name not in cache:
        # Always use rename=True here, as original code intended
        cache[col_name] = namedtuple("Row", [col_name], rename=True)._make
    return cache[col_name]
